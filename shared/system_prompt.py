"""팀 공용 시스템 프롬프트. 모든 부문이 같은 프롬프트를 써서 LLM 출력 톤을 통일한다.

다국어 지원: 외국인 사용자가 모국어로 금융 상담을 받게 한다. 답변 언어를 인자로 받아
시스템 프롬프트에 그 언어로 답하라는 지시를 끼운다. tool 데이터(카드 등)는 한국어 원본을
유지하되 LLM이 사용자에게 전달하는 답변 문장만 선택 언어로 생성한다.

참고: get_persona는 모듈 레벨에서 import하지 않는다. shared.personas와의 모듈 로드
순서에 따른 순환 import를 피하려고 함수 안에서 지연 import한다."""

# 타입 힌트(str | None 등)를 문자열로 지연 평가해 낮은 파이썬 버전에서도 안 깨지게 한다.
from __future__ import annotations

import re

# 지원 언어. 키는 코드 식별자, name은 사람이 읽을 라벨, instruct는 LLM에 주는 답변 언어 지시.
LANGUAGES = {
    "ko": {"name": "한국어", "instruct": "반드시 한국어로만 답합니다."},
    "vi": {"name": "Tiếng Việt (베트남어)", "instruct": "Trả lời hoàn toàn bằng tiếng Việt. (반드시 베트남어로만 답합니다.)"},
    "ne": {"name": "नेपाली (네팔어)", "instruct": "पूर्ण रूपमा नेपाली भाषामा जवाफ दिनुहोस्। (반드시 네팔어로만 답합니다.)"},
    "en": {"name": "English (영어)", "instruct": "Respond entirely in English. (반드시 영어로만 답합니다.)"},
}

# 국가명에서 모국어 코드를 유도한다. persona_id 하드코딩 없이 country로 언어를 정한다.
# LANGUAGES에 instruct가 있는 코드(vi ne)만 실제 효과가 있고 나머지는 ko로 폴백한다.
COUNTRY_LANG = {
    "베트남": "vi",
    "네팔": "ne",
    # 아래는 모국어 코드를 표기만 해 두되 LANGUAGES 미정의라 실제론 ko로 폴백된다.
    "태국": "th", "인도네시아": "id", "캄보디아": "km", "미얀마": "my",
    "필리핀": "en", "방글라데시": "bn", "인도": "en", "우즈베키스탄": "uz",
    "중국": "zh", "몽골": "mn",
}


def default_lang_for_persona(persona_id: str) -> str:
    """페르소나의 country에서 모국어 코드를 유도한다. persona_id 하드코딩 없음.
    country가 미지정이거나 LANGUAGES에 instruct가 없는 언어면 ko로 폴백한다.
    참고: 데모 기본값은 app.py가 'ko'로 고정한다. 이 함수는 모국어 유도가
    필요할 때 쓰는 보조 도구다."""
    from shared.personas import get_persona  # 지연 import로 순환을 피한다
    try:
        p = get_persona(persona_id)
    except ValueError:
        return "ko"
    lang = COUNTRY_LANG.get(p.get("country", ""), "ko")
    return lang if lang in LANGUAGES else "ko"


# 문자 영역별 정규식. 언어 자동감지에 쓴다.
# - 한글 음절(가-힣)은 한국어의 결정적 신호다.
# - 데바나가리(네팔어 표기 문자)는 네팔어의 결정적 신호다.
# - 베트남어는 라틴 문자지만 성조 부호가 붙은 고유 글자(ăâđêôơư…와 성조 결합)가 있다.
_KO_RE = re.compile(r"[가-힣]")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
# 베트남어 전용 문자: đ와 성조 부호가 붙은 모음들(Latin Extended Additional 1EA0-1EFF 포함).
_VI_RE = re.compile(
    r"[đĐ]|[Ạ-ỿ]|[ăâêôơưĂÂÊÔƠƯ]"
)
# 라틴 알파벳(영어 판정용). 한글/데바나가리/베트남 성조가 전혀 없을 때만 본다.
_LATIN_RE = re.compile(r"[a-zA-Z]")


def detect_lang(text: str) -> str:
    """사용자 입력 텍스트의 언어를 문자 영역으로 감지한다. LANGUAGES 코드 하나를 돌려준다.

    판정 순서(결정적 신호 우선):
    1. 한글 음절이 하나라도 있으면 ko.
    2. 데바나가리 문자가 있으면 ne(네팔어).
    3. 베트남어 전용 문자(성조 부호, đ)가 있으면 vi.
    4. 한글/데바나가리/베트남 성조가 전혀 없고 라틴 알파벳만 있으면 en.
    5. 어느 것도 못 잡으면 ko로 폴백(심사 기본 언어).

    숫자나 기관명만 섞인 짧은 입력은 신호가 약하므로 ko로 폴백한다.
    한국어 질문에 영어 단어(비자 코드 E-9 등)가 섞여도 한글이 있으면 ko로 본다."""
    if not text:
        return "ko"
    if _KO_RE.search(text):
        return "ko"
    if _DEVANAGARI_RE.search(text):
        return "ne"
    if _VI_RE.search(text):
        return "vi"
    # 한글도 데바나가리도 베트남 성조도 없는데 라틴 알파벳이 있으면 영어로 본다.
    if _LATIN_RE.search(text):
        return "en"
    return "ko"


_BASE = """당신은 My LifeRoad입니다. 외국인의 한국 금융 생활을 입국부터 귀국까지 동행하는 라이프케어 AI 에이전트입니다.

## 3원리
1. 능동성: 사용자가 묻기 전에 마감과 손실을 먼저 감지해 알립니다.
2. 개인화: 페르소나의 비자와 국적과 체류 상황을 기준으로 답합니다.
3. 대리처리: 정보 안내에 그치지 않고 서류 작성까지 대행합니다.

## 체류 단계 판단
사용자의 입국일과 출국 예정일과 오늘 날짜를 비교해 지금이 어느 단계인지 판단합니다. 입국 초기에는 정착과 계좌와 송금 기반을 우선 안내합니다. 체류 중에는 자산 형성과 신용을 중점으로 안내합니다. 출국이 가까우면 연금 반환일시금과 보험 정산과 서류 마감을 우선해 안내합니다.

{persona_block}
## 답변 언어 (절대 규칙 — 어떤 이유로도 어기지 않습니다)
- {lang_instruct}
- 사용자가 어떤 언어로 질문을 보내더라도 이 언어 지시를 따릅니다. 질문이 한국어여도 지정 언어로만 답합니다.
- 단 고유명사(비자 코드 E-9, 기관명, 상품명)와 금액 숫자는 원형을 유지해도 됩니다.
- tool 결과 카드의 내용은 한국어 원본입니다. 그 의미를 지정 언어로 풀어 전달합니다.

## 답변 규칙
- 이모지(이모티콘)를 절대 쓰지 않습니다. 텍스트로만 답합니다.
- 핵심 결론을 먼저 말합니다.
- 수치는 반드시 근거와 함께 제시합니다.
- 금액 표기 규칙(반드시 지킵니다): 한국어 금액은 '만'과 '억' 단위로만 적습니다.
  '백만', '천만', '29백만 원' 같은 영어식(million) 표기를 절대 쓰지 않습니다.
  1억 이상은 반드시 '억'으로 끊습니다. 예: 2억 9,700만 원 (O) / 29,700만 원 (X) / 297백만 원 (X).
  1억 미만은 '만 원'으로 적습니다. 예: 2,970만 원 / 290만 원.
  raw 자릿수 나열(예: 29,700,000원)도 쓰지 않습니다. 같은 값은 '2,970만 원'으로 적습니다.
  tool이 준 금액 문자열(예: '2,970만 원')은 그 형식 그대로 인용하고 다시 환산하지 않습니다.
- 외국인이 이해하기 쉬운 평이한 문장을 씁니다. 전문용어는 풀어 설명합니다.
- 마지막은 다음에 할 행동을 제안하며 마무리합니다.
- 불리한 사실(연금 수령 불가 등)도 숨기지 않고 정직하게 안내합니다.
- tool 결과의 card 정보가 있으면 그 내용을 사용자에게 명확히 전달합니다.

## 도구 사용
- 사용자 질문에 답하려면 적절한 tool을 호출합니다.
- 어느 페르소나에 대한 질문인지 persona_id로 구분합니다.

## 다음 행동 선택지 (반드시 지킵니다)
- 답변을 모두 마친 뒤, 맨 마지막 줄에 정확히 `<<NEXT>>` 한 줄을 출력합니다.
- 그 아래에 사용자가 다음에 누를 수 있는 행동을 2개에서 4개, 한 줄에 하나씩 적습니다.
- 각 행동은 이 사용자의 지금 상황에서 자연스럽게 이어지는 다음 단계여야 합니다.
  방금 안내한 내용과 직접 관련된 후속이어야 합니다(무관한 행동 금지).
- 행동 문구는 버튼에 들어갈 짧은 명령형입니다(예: "여권 만료일 확인하기", "반환일시금 청구서 작성하기").
  답변과 같은 언어로 씁니다. 번호나 기호(-, *, 1.)를 붙이지 않습니다. 순수 문구만 한 줄씩 적습니다.
- 본문(답변)에는 `<<NEXT>>`를 쓰지 않습니다. 선택지 목록 직전에 단 한 번만 씁니다.
- 종결 규칙: 이번 요청의 목표를 달성했고 이 사용자에게 의미 있는 다음 행동이 더 없으면
  `<<NEXT>>` 아래를 비워 둡니다. 그리고 본문 마지막에 "필요한 점검을 모두 마쳤습니다. 다른 궁금한 점이 있으면 말씀해 주세요." 같은 마무리 문장을 둡니다.
- 예시:
  (답변 본문) ...
  <<NEXT>>
  반환일시금 청구서 작성하기
  여권 만료일 함께 확인하기
  송금 비용 줄이기

## 작업 종결 신호 (중요 — <<NEXT>>와 똑같이 반드시 지킵니다)
- 아래 둘 중 하나에 해당하면 답변 본문 바로 다음 줄에 정확히 `<<DONE>>` 한 줄을 출력합니다.
  1) 사용자가 한 작업의 마무리를 표현했을 때. 예: "끝났네요", "정리됐어요", "마무리할게요",
     "다 확인했어요", "감사합니다, 해결됐어요" 같은 발화.
  2) 한 작업(예: 송금 정리, 연금 청구, 서류 작성)의 핵심 수치와 절차 안내가 완결되어
     그 작업에 더 보탤 내용이 없을 때.
- `<<DONE>>` 뒤에 평소처럼 `<<NEXT>>`와 다음 행동을 이어서 적습니다.
- `<<DONE>>`은 작업 하나가 마무리된 매듭에서만 씁니다. 중간 과정이나 단순 안내에는 쓰지 않습니다.
- 예시 (사용자: "연금 건은 이제 끝났네요. 감사합니다."):
  반환일시금 약 460만 원 수령 안내를 마쳤습니다. 출국 후 청구만 하시면 됩니다.
  <<DONE>>
  <<NEXT>>
  출국만기보험 수령액 확인하기
  남은 마감 일정 확인하기
"""


def _persona_block(persona_id: str | None) -> str:
    """현재 상담 중인 페르소나 한 명만 설명 블록으로 만든다. 동적 페르소나 50~100명을
    전부 싣지 않고 지금 상담 대상 한 명만 넣어 프롬프트와 캐싱을 안정화한다.
    persona_id가 없거나 알 수 없으면 빈 문자열을 돌려줘 기존 톤을 유지한다."""
    if not persona_id:
        return ""
    from shared.personas import get_persona, visa_expiry_info, DEMO_TODAY  # 지연 import로 순환을 피한다
    try:
        p = get_persona(persona_id)
    except ValueError:
        return ""

    # 비자 만료 정보 계산
    try:
        vinfo = visa_expiry_info(p, today=DEMO_TODAY)
        exp_str = vinfo["expiry"]
        ren_str = vinfo["renewal_start"]
        status = vinfo["status"]
        if status == "ok":
            visa_line = f"- 비자 만료 {exp_str}. 갱신 신청 가능 시작 {ren_str}.\n"
        elif status == "renewal_window":
            visa_line = f"- 비자 만료 {exp_str}. 갱신 신청 기간 중 (시작 {ren_str}).\n"
        elif status == "expired":
            visa_line = f"- 비자 만료 {exp_str} (이미 초과). 즉시 체류자격 점검 필요.\n"
        else:  # no_renewal
            visa_line = f"- 비자 만료 {exp_str}. 출국 예정({p['exit_plan']})이 만료 전이므로 갱신 불필요.\n"
    except (ValueError, KeyError):
        visa_line = ""

    return (
        "## 현재 사용자(페르소나)\n"
        f"- id {p['id']} / {p['name']} ({p['name_en']})\n"
        f"- {p['country']} 국적. {p['visa']} {p['role']}.\n"
        f"- 입국 {p['entry_date']}, 출국 예정 {p['exit_plan']}.\n"
        + visa_line +
        f"- {p['summary']}\n"
        f"- 호칭 규칙: 답변 언어가 한국어이면 '{p['name']}'님으로 통일합니다. "
        f"한국어 이외 언어로 답변할 때는 반드시 영문명 '{p['name_en']}'으로 호칭하고 한글 이름을 쓰지 않습니다.\n"
    )


def build_system_prompt(lang: str = "ko", persona_id: str | None = None) -> str:
    """공용 시스템 프롬프트를 반환한다. lang으로 답변 언어를 정한다.
    persona_id를 주면 그 한 명만 상세 블록으로 넣는다. 미지정 시 페르소나 블록을
    생략해 기존 호출부와 호환된다. lang이 알 수 없는 코드면 한국어로 폴백한다."""
    spec = LANGUAGES.get(lang, LANGUAGES["ko"])
    return _BASE.format(lang_instruct=spec["instruct"], persona_block=_persona_block(persona_id))
