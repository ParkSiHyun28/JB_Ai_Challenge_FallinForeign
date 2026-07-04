"""streamlit 의존을 제거한 순수 코어.

옛 streamlit 앱에서 UI 무관 로직만 추출했다. 마커 분리, tool 디스패치,
능동 점검 계획, 다국어 라벨, 첫 화면 AI 인트로 추천을 담는다.
백엔드(FastAPI)와 테스트가 이 모듈만 import 하면 streamlit 없이 동작한다.
"""

from __future__ import annotations

import os
import re

from shared.system_prompt import build_system_prompt, LANGUAGES
from shared.personas import get_persona, DEMO_TODAY_STR
from shared.registry import TOOL_REGISTRY
from shared.llm_provider import run_chat, strip_emoji, CLAUDE_MODEL_CHAT, CLAUDE_MODEL_DOCS

# 데모 기준일. 민 출국 D-90 무렵. 원본은 shared/personas.py의 DEMO_TODAY_STR 한 곳이다.
TODAY = DEMO_TODAY_STR

# tool 이름을 사람이 읽을 한글 단계명으로. 처리 과정 패널 라벨에 쓴다.
TOOL_LABELS = {
    "deadline_radar": "마감 D-Day 추적",
    "pension_estimator": "연금 반환일시금 산출",
    "collateral_calc": "예금담보대출 한도 계산",
    "remit_optimizer": "송금 경로 최적화",
    "credit_builder": "대안신용 축적도 추정",
    "form_autofill": "신청서 자동작성",
}

_NEXT_MARKER = "<<NEXT>>"
_DONE_MARKER = "<<DONE>>"


# ---------------------------------------------------------------------------
# 마커 분리 (app.py에서 그대로 이식)
# ---------------------------------------------------------------------------

def split_answer_and_actions(text: str) -> tuple[str, list[str]]:
    """LLM 답변에서 본문과 후속 선택지 라벨을 분리한다.

    LLM은 답변 끝에 `<<NEXT>>` 한 줄을 두고 그 아래 후속 행동을 한 줄씩 적도록 지시받는다.
    이 함수는 마커 앞은 화면에 보일 본문으로, 마커 뒤 각 줄은 버튼 라벨로 가른다.
    마커가 없으면 본문 전체를 그대로 두고 빈 라벨 리스트를 돌려준다.
    스트리밍 중 꼬리가 마커 접두사(<<NEXT 또는 <)로 끝나면 그 앞까지만 본문으로 쓴다.
    """
    if not text:
        return text, []
    partial_marker_prefixes = ("<<NEXT>>", "<<NEXT>", "<<NEXT", "<<NEX", "<<NE", "<<N", "<<")
    if _NEXT_MARKER not in text:
        for prefix in partial_marker_prefixes[1:]:  # <<NEXT>> 제외(완전한 마커)
            if text.endswith(prefix):
                return text[: -len(prefix)].rstrip(), []
        return text, []
    idx = text.rfind(_NEXT_MARKER)
    body = text[:idx]
    tail = text[idx + len(_NEXT_MARKER):]
    if not body.strip():
        # 본문 없이 마커로 시작한 비정상 응답. 마커가 화면에 노출되지 않게 제거만 하고
        # 나머지 텍스트를 본문으로 쓴다(라벨 추출은 포기).
        return text.replace(_NEXT_MARKER, "").strip(), []
    labels: list[str] = []
    for raw in tail.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*•]\s*", "", line)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        line = line.strip().strip('"').strip("'").strip()
        if not line or len(line) > 40:
            continue
        if line.endswith((".", "다", "요")) and len(line) > 28:
            continue
        labels.append(line)
        if len(labels) >= 4:
            break
    return body.rstrip(), labels


def parse_done_marker(text: str) -> tuple[str, bool]:
    """LLM 답변에서 <<DONE>> 마커를 찾아 제거하고 is_done 불리언을 함께 반환한다."""
    if _DONE_MARKER not in text:
        return text, False
    cleaned = text.replace(_DONE_MARKER, "").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, True


def strip_streaming_markers(text: str) -> str:
    """스트리밍 중 누적 텍스트에서 마커와 부분 마커를 화면 표시용으로 제거한다.

    프론트가 token 이벤트를 누적하며 호출한다. 완전한 <<NEXT>>/<<DONE>> 뒤를 자르고,
    꼬리가 마커 접두사로 끝나면 그 앞까지만 보인다(깜빡임 방지).
    백엔드 final 이벤트가 권위 있는 본문을 보내므로 여기선 표시 품질만 담당한다.
    """
    if not text:
        return text
    # 완전한 <<NEXT>> 이후 전부 제거
    if _NEXT_MARKER in text:
        text = text[: text.find(_NEXT_MARKER)].rstrip()
    # <<DONE>> 제거
    text = text.replace(_DONE_MARKER, "")
    # 꼬리 부분 마커 숨김
    for prefix in ("<<NEXT>", "<<NEXT", "<<NEX", "<<NE", "<<N", "<<DONE", "<<DON", "<<DO", "<<D", "<<"):
        if text.endswith(prefix):
            return text[: -len(prefix)].rstrip()
    return text


# ---------------------------------------------------------------------------
# tool 디스패치 (app.py에서 그대로 이식)
# ---------------------------------------------------------------------------

def run_tool(name: str, args: dict) -> dict:
    """tool을 실제 실행한다. deadline_radar의 as_of는 항상 데모 기준일로 강제한다.
    호출자의 args dict를 변형하지 않도록 복사본에 주입한다."""
    if name not in TOOL_REGISTRY:
        raise RuntimeError(
            f"알 수 없는 tool: {name}. 사용 가능: {list(TOOL_REGISTRY.keys())}"
        )
    call_args = dict(args)
    if name == "deadline_radar":
        call_args["as_of"] = TODAY
    return TOOL_REGISTRY[name](**call_args)


# ---------------------------------------------------------------------------
# 턴별 모델 라우팅 (채팅=Haiku 빠르게 / 서류=Sonnet 정확하게)
# ---------------------------------------------------------------------------

# 서류 작성 턴 판별 키워드. 사용자 발화나 선택지 라벨에 이 단어가 있으면
# 그 턴을 서류용 모델(Sonnet)로 돌린다. PDF 채움 계산은 결정적 코드지만
# 어떤 서류인지 판단과 안내 문장의 정확성이 중요해서 상위 모델을 쓴다.
_DOCS_KEYWORDS = ("서류", "신청서", "작성", "확인서", "양식", "pdf", "PDF")


def pick_model(intent: str) -> str:
    """이 턴에 쓸 Claude 모델을 고른다.

    서류 관련 발화면 CLAUDE_MODEL_DOCS(Sonnet), 그 외는 CLAUDE_MODEL_CHAT(Haiku).
    """
    text = intent or ""
    if any(k in text for k in _DOCS_KEYWORDS):
        return CLAUDE_MODEL_DOCS
    return CLAUDE_MODEL_CHAT


# ---------------------------------------------------------------------------
# 서류 PDF 다운로드 (채팅 카드에 다운로드 정보 부착)
# ---------------------------------------------------------------------------

def attach_download(card: dict | None, numbers: dict | None) -> dict | None:
    """tool 결과 카드에 PDF 다운로드 정보를 붙인다.

    form_autofill이 numbers.output_pdf_path에 생성 PDF 경로를 담아 준다.
    경로가 있으면 카드 사본에 download_url(백엔드 /download 상대경로)을 넣는다.
    카드가 없거나 PDF가 없으면 원본을 그대로 돌려준다. 원본 card를 변형하지 않는다."""
    if not card:
        return card
    path = (numbers or {}).get("output_pdf_path")
    if not path:
        return card
    out = dict(card)
    out["download_url"] = "/download/" + os.path.basename(path)
    return out


def download_filename(filename: str) -> str:
    """저장 파일명({persona}_{form_id}_filled.pdf)을 받는 사람용 한글 파일명으로 바꾼다.

    알려진 form_id가 꼬리에 있으면 그 한글 양식명을 쓴다. 못 찾으면 원래 이름 그대로."""
    from mcp_servers.docs.data import GOVERNMENT_FORMS
    for fid, meta in GOVERNMENT_FORMS.items():
        if filename.endswith(f"{fid}_filled.pdf"):
            return f"{meta['name_ko']}.pdf"
    return filename


# ---------------------------------------------------------------------------
# 능동 점검 계획과 다국어 라벨 (app.py에서 그대로 이식)
# ---------------------------------------------------------------------------

def active_plan(persona_id: str) -> list[tuple[str, dict]]:
    """페르소나 속성으로 능동 점검 계획을 만든다. persona_id 하드코딩 없이
    visa wage deposit pension 값으로 어떤 tool이 의미 있는지 판단한다.

    주의: 이 계획과 TOOL_LABELS와 ACTION_LABELS는 asset과 docs tool 이름을 직접 안다.
    새 부문(fraud 등)을 붙이면 대화 모드는 registry로 자동 연결되지만
    능동 점검과 라벨은 여기를 함께 갱신해야 한다."""
    p = get_persona(persona_id)
    plan: list[tuple[str, dict]] = []
    if p["visa"] == "E-9":
        plan.append(("deadline_radar", {"persona_id": persona_id}))
    if p["monthly_remit_krw"] > 0:
        plan.append(("remit_optimizer", {"persona_id": persona_id}))
    # 연금: 납부 이력이 있으면 점검한다. 수령 가능 여부는 tool이 국가 테이블로 스스로
    # 판정하므로(2026-07 고도화) 여기서 treaty bool을 보지 않는다.
    if p["pension_months"] > 0:
        plan.append(("pension_estimator", {"persona_id": persona_id}))
    if p["deposit_balance_krw"] > 0:
        plan.append(("collateral_calc", {"persona_id": persona_id}))
    # 신용: 축적 이력이 있거나 Thin Filer(무소득+예치금 보유)면 점검한다.
    # 축적 개월은 tool이 credit_accrual_start 필드에서 계산한다(고정값 제거).
    if p.get("credit_accrual_start") or (p["monthly_wage_krw"] == 0 and p["deposit_balance_krw"] > 0):
        plan.append(("credit_builder", {"persona_id": persona_id}))
    form_id = "departure_insurance_claim" if p["visa"] == "E-9" else "alien_registration_renewal"
    plan.append(("form_autofill", {"form_id": form_id, "persona_id": persona_id}))
    return plan


ACTION_LABELS = {
    "deadline_radar": {
        "ko": "마감 기한 확인하기", "en": "Check upcoming deadlines",
        "vi": "Kiểm tra hạn chót sắp tới", "ne": "आउँदो म्याद जाँच गर्नुहोस्",
    },
    "pension_estimator": {
        "ko": "연금 반환일시금 계산하기", "en": "Estimate my pension refund",
        "vi": "Tính tiền hoàn bảo hiểm hưu trí", "ne": "पेन्सन फिर्ता रकम अनुमान गर्नुहोस्",
    },
    "collateral_calc": {
        "ko": "예금담보대출 한도 계산하기", "en": "Calculate my loan limit",
        "vi": "Tính hạn mức vay thế chấp", "ne": "ऋण सीमा गणना गर्नुहोस्",
    },
    "remit_optimizer": {
        "ko": "송금 비용 줄이기", "en": "Lower my remittance cost",
        "vi": "Giảm phí chuyển tiền", "ne": "रेमिट्यान्स लागत घटाउनुहोस्",
    },
    "credit_builder": {
        "ko": "신용 점수 쌓기 시작하기", "en": "Start building my credit",
        "vi": "Bắt đầu xây dựng tín dụng", "ne": "क्रेडिट निर्माण सुरु गर्नुहोस्",
    },
    "form_autofill": {
        "ko": "신청서 자동으로 작성하기", "en": "Auto-fill the application form",
        "vi": "Tự động điền đơn", "ne": "आवेदन फारम स्वतः भर्नुहोस्",
    },
}

NEXT_HEADER = {
    "ko": "다음으로 무엇을 도와드릴까요?",
    "en": "What would you like me to do next?",
    "vi": "Tiếp theo bạn muốn tôi làm gì?",
    "ne": "अब म तपाईंलाई के मद्दत गरूँ?",
}

START_HEADER = {
    "ko": "이런 것을 도와드릴 수 있습니다. 무엇부터 할까요?",
    "en": "Here is how I can help. Where shall we start?",
    "vi": "Tôi có thể giúp những việc sau. Bắt đầu từ đâu?",
    "ne": "म यी कुराहरूमा मद्दत गर्न सक्छु। कहाँबाट सुरु गरौं?",
}

DONE_CAPTION = {
    "ko": "필요한 점검을 모두 마쳤습니다. 다른 궁금한 점이 있으면 말씀해 주세요.",
    "en": "All checks are complete. Let me know if you have other questions.",
    "vi": "Đã hoàn tất mọi kiểm tra. Nếu bạn còn câu hỏi, hãy cho tôi biết.",
    "ne": "सबै जाँच सकियो। अरू प्रश्न भए सोध्नुहोस्।",
}


def start_action_labels(
    persona_id: str,
    reply_lang: str,
    limit: int = 3,
    exclude_tools: set | None = None,
) -> list[str]:
    """첫 화면 선제 선택지 라벨을 만든다(정적, 페르소나 기반)."""
    plan = active_plan(persona_id)
    excluded = exclude_tools or set()
    out: list[str] = []
    seen: set[str] = set()
    for tname, _ in plan:
        if tname in seen or tname not in ACTION_LABELS:
            continue
        if tname in excluded:
            continue
        seen.add(tname)
        label = ACTION_LABELS.get(tname, {}).get(reply_lang) \
            or ACTION_LABELS.get(tname, {}).get("ko") or tname
        out.append(label)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# 첫 화면 AI 인트로 추천 (app.py에서 이식, 캐싱은 streamlit → 모듈 dict)
# ---------------------------------------------------------------------------

_INTRO_CACHE: dict[str, tuple[str, list[str]]] = {}


def ai_recommend_actions(
    persona_id: str,
    reply_lang: str,
    exclude_tools: set | None = None,
) -> tuple[str, list[str]]:
    """LLM이 페르소나 상황을 읽고 첫 화면 추천 행동을 동적으로 생성한다.

    반환: (인사+상황요약 본문, 추천 라벨 리스트).
    LLM 호출 실패 또는 라벨이 비면 정적 폴백(start_action_labels)을 쓴다.
    결과는 모듈 dict _INTRO_CACHE에 persona+lang 키로 캐싱한다.
    exclude_tools가 있으면 캐싱하지 않는다(완료 tool 상태가 매번 다르므로).
    """
    excluded = exclude_tools or set()
    cache_key = f"{persona_id}__{reply_lang}"
    if not excluded and cache_key in _INTRO_CACHE:
        return _INTRO_CACHE[cache_key]

    p = get_persona(persona_id)
    lang_directive = LANGUAGES[reply_lang]["instruct"]

    exclude_note = ""
    if excluded:
        done_labels = [
            ACTION_LABELS.get(t, {}).get("ko") or t
            for t in excluded
            if t in ACTION_LABELS
        ]
        if done_labels:
            exclude_note = f" 이미 처리한 작업은 제외해 줘: {', '.join(done_labels)}."

    # 첫 화면 인트로는 모든 페르소나가 같은 템플릿 구조로 나오게 강제한다.
    # 시작 문구("{이름}님은 현재")와 3개 문단 구조를 고정하고 내용만 페르소나별로 채운다.
    name = p["name"]
    user_text = (
        f"[페르소나: {persona_id}] [답변 언어 강제: {lang_directive}] "
        f"오늘은 {TODAY}입니다. "
        f"이 사용자의 비자와 입국일과 출국 예정일과 오늘 날짜와 자산과 연금 납부 상황을 종합해 "
        f"첫 화면 인트로를 작성해 줘. 아래 템플릿 구조를 반드시 그대로 지켜라.\n\n"
        f"1번째 문단: 반드시 '{name}님은 현재'로 시작해서 지금 처한 핵심 상황을 한 문장으로 요약한다"
        f"(체류 단계와 남은 기간 중심).\n"
        f"2번째 문단: 지금 챙기지 않으면 놓치는 금액이나 기회를 구체 수치로 한 문장.\n"
        f"3번째 문단: '지금부터 준비하면 됩니다' 같은 안내로 마무리.\n"
        f"세 문단은 각각 한 문장씩이고, 문단과 문단 사이는 반드시 빈 줄 하나로 띄워 문단을 나눠라"
        f"(가독성). 한 덩어리로 이어 붙이지 마라.\n"
        f"그 뒤 <<NEXT>>로 지금 가장 먼저 챙겨야 할 금융 행동 3개를 우선순위로 적는다.\n"
        f"문단은 3개를 넘기지 말고 각 문장은 짧게. 같은 페르소나는 항상 같은 구조로 답해야 한다."
        f"{exclude_note}"
    )

    fallback_body = (
        f"{p['name']}님은 현재 한국 체류 상황을 점검할 시점입니다.\n\n"
        f"지금부터 하나씩 준비하면 됩니다."
    )
    fallback_labels = start_action_labels(persona_id, reply_lang, exclude_tools=excluded)

    system = build_system_prompt(reply_lang, persona_id)
    try:
        raw = run_chat(user_text, system, run_tool)
        raw = strip_emoji(raw)
        raw, _ = parse_done_marker(raw)
        body, labels = split_answer_and_actions(raw)
        if not labels:
            labels = fallback_labels
        if not body.strip():
            body = fallback_body
    except Exception:
        body = fallback_body
        labels = fallback_labels

    result = (body, labels)
    if not excluded:
        _INTRO_CACHE[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# 멀티턴 히스토리 (app.py _build_history를 프론트가 보낸 messages용으로 변형)
# ---------------------------------------------------------------------------

def build_history(messages: list[dict], max_turns: int = 3) -> list[dict]:
    """프론트가 보낸 대화 메시지에서 직전 최대 max_turns 턴을 LLM 히스토리로 변환한다.

    messages는 [{"role": "user"|"assistant", "content": str}, ...] 형식.
    user/assistant 쌍을 뒤에서 max_turns개 잘라 시간순으로 돌려준다.
    현재 발화는 호출부에서 user_text로 별도 전달하므로 포함하지 않는다(호출부 책임).
    """
    pairs: list[tuple[str, str]] = []
    i = len(messages) - 1
    while i >= 0 and len(pairs) < max_turns:
        m = messages[i]
        if m.get("role") == "assistant":
            asst_text = m.get("content", "")
            j = i - 1
            while j >= 0 and messages[j].get("role") != "user":
                j -= 1
            if j >= 0:
                user_text = messages[j].get("content", "")
                pairs.append((user_text, asst_text))
                i = j - 1
            else:
                break
        else:
            i -= 1
    pairs.reverse()
    history: list[dict] = []
    for u, a in pairs:
        history.append({"role": "user", "content": u})
        history.append({"role": "assistant", "content": a})
    return history


def korean_error_msg(e: Exception) -> str:
    """예외를 종류별 한국어 안내 문구로 변환한다."""
    try:
        import anthropic as _ant
        if isinstance(e, _ant.RateLimitError):
            return "지금 요청이 몰려 잠시 후 다시 시도해 주세요."
        if isinstance(e, (_ant.APITimeoutError, _ant.APIConnectionError)):
            return "응답이 지연됩니다. 잠시 후 다시 시도해 주세요."
    except ImportError:
        pass
    msg = str(e)
    if "API 키" in msg or "ANTHROPIC_API_KEY" in msg or "key" in msg.lower():
        return "API 키 설정이 필요합니다. 환경변수(ANTHROPIC_API_KEY)를 확인해 주세요."
    return "일시적인 오류가 발생했습니다. 다시 시도해 주세요."


# ---------------------------------------------------------------------------
# 페르소나 카드 데이터 (sync_helper 매핑을 백엔드 응답용으로 이식)
# ---------------------------------------------------------------------------

def persona_card(p: dict) -> dict:
    """페르소나 dict를 프론트 셸 카드가 기대하는 키로 변환한다.
    비자 만료/갱신 정보까지 포함한다(visa_expiry_info)."""
    from shared.personas import visa_expiry_info

    card: dict = {
        "id": p.get("id", ""),
        "code": p.get("flag", ""),
        "name": p.get("name", ""),
        "en": p.get("name_en", ""),
        "nationality": p.get("country", ""),
        "visa": p.get("visa", ""),
        "entry": p.get("entry_date", ""),
        "exit": p.get("exit_plan", ""),
        "note": p.get("summary", ""),
    }
    try:
        vinfo = visa_expiry_info(p)
        card["visaExpiry"] = vinfo.get("expiry", "")
        card["visaRenewal"] = vinfo.get("renewal_start", "")
        card["visaMonthsLeft"] = vinfo.get("months_left", 0)
        card["visaStatus"] = vinfo.get("status", "")
        card["visaRenewalNeeded"] = vinfo.get("renewal_needed", False)
    except Exception:
        card["visaExpiry"] = ""
        card["visaRenewal"] = ""
        card["visaMonthsLeft"] = 0
        card["visaStatus"] = ""
        card["visaRenewalNeeded"] = False
    return card
