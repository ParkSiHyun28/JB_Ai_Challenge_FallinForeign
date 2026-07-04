"""agent/verification_chat.py — 모국어 본인확인 대화 1턴 처리.

이 모듈은 사기 리스크를 다시 점수화하지 않는다. 이미 보류/검토된 케이스에서 고객 답변을
읽고, 상담사가 볼 수 있는 intent·한국어 요약·다음 확인 메시지·라우팅 후보를 만든다.
core 는 LLM·HTTP·상태를 모른다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from contracts.verification_chat import (
    VerificationIntent,
    VerificationNextState,
    VerificationTurnInput,
    VerificationTurnOutput,
)

MAX_TOKENS = 1200

_LANG_NAMES = {
    "ko": "Korean",
    "vi": "Vietnamese",
    "ne": "Nepali (Devanagari script)",
    "en": "English",
    "id": "Indonesian",
    "zh": "Chinese",
    "th": "Thai",
}
_LANG_SCRIPT = {"ko": "hangul", "vi": "latin", "en": "latin", "id": "latin", "ne": "devanagari"}

_INTENTS = {i.value for i in VerificationIntent}


def _safe_json_loads(text: str) -> Optional[dict]:
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None


def _money(v) -> str:
    try:
        return f"{float(v):,.0f}원"
    except Exception:
        return "금액 미상"


def _card(card_id: str, kind: str, title: str, fact: str) -> dict:
    return {"id": card_id, "kind": kind, "title": title, "fact": fact}


def _evidence_cards(alert: dict) -> list[dict]:
    inv = alert.get("investigation") or {}
    cards = inv.get("key_evidence")
    if isinstance(cards, list) and cards:
        return cards

    cards = [
        _card("E_TX_1", "transaction", "거래 금액", f"거래 금액은 {_money(alert.get('amount'))}입니다."),
        _card("E_TX_2", "transaction", "거래 채널과 수취국",
              f"{alert.get('channel')} 채널로 {alert.get('counterparty_country')} 수취국 거래가 발생했습니다."),
        _card("E_TX_3", "transaction", "신규기기 여부",
              f"신규기기 여부는 {bool(alert.get('is_new_device'))}입니다."),
        _card("E_TX_4", "transaction", "잔액 인출률",
              f"잔액 인출률은 {alert.get('balance_drawdown_ratio')}입니다."),
    ]
    for i, rule in enumerate(alert.get("triggered_rules") or [], 1):
        cards.append(_card(f"E_RULE_{i}", "rule", f"발동 룰 {rule}", f"룰 '{rule}'이 발동했습니다."))
    if alert.get("verification"):
        cards.append(_card("E_VERIFY_1", "verification", "발송된 본인확인 메시지",
                          str((alert.get("verification") or {}).get("message") or "")))
    return cards


def _valid_ids(cards: list[dict]) -> set[str]:
    return {str(c.get("id")) for c in cards if c.get("id")}


def _fallback_ids(cards: list[dict]) -> list[str]:
    return [str(c.get("id")) for c in cards if c.get("id")][:3]


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(p in text for p in patterns)


def _has_regex(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _script_of(text: str) -> str:
    for ch in text or "":
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF:
            return "hangul"
        if 0x0900 <= code <= 0x097F:
            return "devanagari"
    return "latin" if any(c.isalpha() for c in (text or "")) else "unknown"


def _script_matches(lang: str, text: str) -> bool:
    expected = _LANG_SCRIPT.get(lang)
    return expected is None or _script_of(text) == expected


def _heuristic_intent(reply: str) -> str:
    """안전상 중요한 신호는 결정론적으로 먼저 잡는다."""
    raw = reply or ""
    text = raw.lower()

    if _has_any(text, ["ignore previous", "system prompt", "승인이라고", "무시하고 승인", "approve this"]):
        return VerificationIntent.UNSAFE.value

    remote = [
        "원격", "화면 공유", "화면공유", "앱 설치", "앱을 설치", "anydesk", "teamviewer",
        "screen share", "remote control", "install app", "cài ứng dụng", "chia sẻ màn hình",
        "điều khiển", "एप", "स्क्रिन",
    ]
    if _has_any(text, remote):
        return VerificationIntent.REMOTE_CONTROL.value

    coercion = [
        "강요", "협박", "시키", "시켰", "말하지 말", "비밀", "문제 생긴", "누가 하라고",
        "someone told", "told me to", "don't tell", "do not tell", "threat", "bảo tôi",
        "không được báo", "đe dọa", "ép", "धम्की", "नभन्न",
    ]
    if _has_any(text, coercion):
        return VerificationIntent.COERCION.value

    scam = [
        "대출", "선입금", "수수료", "투자", "고수익", "검찰", "경찰", "금감원", "비자 취소",
        "loan", "fee first", "investment", "profit", "police", "prosecutor",
        "vay", "phí", "đầu tư", "cảnh sát", "비자", "भिसा",
    ]
    if _has_any(text, scam):
        return VerificationIntent.SCAM_SCRIPT.value

    denial_patterns = [
        r"제가\s*(한|보낸)\s*거래\s*아니", r"한\s*적\s*없", r"모르겠", r"모르는\s*거래",
        r"not\s+me", r"did\s*not", r"didn't", r"i\s+don't\s+know", r"không", r"khong",
        r"tôi\s+không", r"không\s+biết", r"होइन", r"गरेको\s+छैन", r"थाहा\s+छैन",
    ]
    denies = _has_regex(raw, denial_patterns)

    confirmed_patterns = [
        r"제가\s*(했|보냈)", r"맞아", r"맞습니다", r"본인", r"yes", r"i\s+did",
        r"authorized", r"i\s+sent", r"đúng", r"tôi\s+đã", r"có", r"हो", r"मैले",
    ]
    confirmed = _has_regex(raw, confirmed_patterns)

    unknown_counterparty = _has_any(text, ["수취인", "누군지 몰", "이름은 몰", "friend of a friend", "don't know who"])
    if confirmed and (denies or unknown_counterparty):
        return VerificationIntent.INCONSISTENT.value
    if denies:
        return VerificationIntent.DENIES.value
    if confirmed:
        return VerificationIntent.CONFIRMED.value
    return VerificationIntent.UNCLEAR.value


def _route(intent: str) -> str:
    if intent == VerificationIntent.CONFIRMED.value:
        return VerificationNextState.RELEASE_CANDIDATE.value
    if intent == VerificationIntent.DENIES.value:
        return VerificationNextState.ACCOUNT_TAKEOVER.value
    if intent in (VerificationIntent.COERCION.value, VerificationIntent.REMOTE_CONTROL.value,
                  VerificationIntent.SCAM_SCRIPT.value):
        return VerificationNextState.PROTECTIVE_ESCALATION.value
    if intent == VerificationIntent.UNSAFE.value:
        return VerificationNextState.MANUAL_REVIEW.value
    return VerificationNextState.KEEP_HOLD.value


def _confidence(intent: str) -> str:
    if intent in (VerificationIntent.COERCION.value, VerificationIntent.REMOTE_CONTROL.value,
                  VerificationIntent.DENIES.value, VerificationIntent.SCAM_SCRIPT.value):
        return "high"
    if intent in (VerificationIntent.CONFIRMED.value, VerificationIntent.INCONSISTENT.value):
        return "medium"
    return "low"


def _summary(intent: str, reply: str) -> str:
    m = {
        VerificationIntent.CONFIRMED.value: "고객이 본인 거래라고 답했습니다. 단, 담당자가 거래 금액·수취인·목적 일치 여부를 확인해야 합니다.",
        VerificationIntent.DENIES.value: "고객이 거래를 부인했습니다. 계정탈취 또는 무단거래 가능성이 있어 보류 유지가 필요합니다.",
        VerificationIntent.COERCION.value: "고객 답변에 제3자 지시·비밀유지·강요 가능성을 시사하는 표현이 있습니다.",
        VerificationIntent.REMOTE_CONTROL.value: "고객 답변에 원격제어 앱 설치나 화면 공유 가능성을 시사하는 표현이 있습니다.",
        VerificationIntent.SCAM_SCRIPT.value: "고객 답변에 대출·투자·기관사칭 등 사기 시나리오와 맞닿은 표현이 있습니다.",
        VerificationIntent.INCONSISTENT.value: "고객 답변이 본인 확인과 수취인 인지 사이에서 모순되거나 애매합니다.",
        VerificationIntent.UNSAFE.value: "고객 답변이 업무 확인과 무관하거나 시스템 지시를 조작하려는 표현을 포함합니다.",
        VerificationIntent.UNCLEAR.value: "고객 답변만으로 본인 거래 여부와 강요 가능성을 판단하기 어렵습니다.",
    }
    preview = reply.strip().replace("\n", " ")[:120]
    return f"{m.get(intent, m[VerificationIntent.UNCLEAR.value])} 고객 답변: “{preview}”"


def _message(lang: str, next_state: str) -> str:
    ko = {
        VerificationNextState.RELEASE_CANDIDATE.value:
            "확인해 주셔서 감사합니다. 담당자가 거래 정보와 일치 여부를 검토한 뒤 안내드리겠습니다.",
        VerificationNextState.ACCOUNT_TAKEOVER.value:
            "고객님 보호를 위해 해당 거래를 계속 보류하겠습니다. 본인이 요청하지 않은 거래라면 비밀번호를 변경하고 은행 상담원 안내를 기다려 주세요.",
        VerificationNextState.PROTECTIVE_ESCALATION.value:
            "안전을 위해 거래를 계속 보류하겠습니다. 누구의 지시를 받고 있거나 은행에 말하지 말라는 요청을 받았다면 더 이상 송금하지 말고 은행 상담원의 안내를 따라 주세요.",
        VerificationNextState.MANUAL_REVIEW.value:
            "답변을 확인했습니다. 안전한 확인을 위해 담당자가 추가로 검토하겠습니다.",
        VerificationNextState.KEEP_HOLD.value:
            "확인을 위해 추가 질문이 필요합니다. 이 거래의 수취인과 송금 목적을 알고 계신지 답변해 주세요.",
    }
    en = {
        VerificationNextState.RELEASE_CANDIDATE.value:
            "Thank you. A bank officer will compare your answer with the transaction details before proceeding.",
        VerificationNextState.ACCOUNT_TAKEOVER.value:
            "For your protection, we will keep this transfer on hold. If you did not request it, please change your password and wait for bank guidance.",
        VerificationNextState.PROTECTIVE_ESCALATION.value:
            "For your safety, we will keep this transfer on hold. If someone instructed you or told you not to tell the bank, please stop sending money and follow bank guidance.",
        VerificationNextState.MANUAL_REVIEW.value:
            "We received your reply. A bank officer will review it for your safety.",
        VerificationNextState.KEEP_HOLD.value:
            "We need one more check. Please tell us whether you know the recipient and the purpose of this transfer.",
    }
    vi = {
        VerificationNextState.RELEASE_CANDIDATE.value:
            "Cảm ơn bạn đã xác nhận. Nhân viên ngân hàng sẽ đối chiếu câu trả lời với thông tin giao dịch trước khi xử lý.",
        VerificationNextState.ACCOUNT_TAKEOVER.value:
            "Để bảo vệ bạn, chúng tôi sẽ tiếp tục tạm giữ giao dịch này. Nếu bạn không yêu cầu giao dịch, vui lòng đổi mật khẩu và chờ hướng dẫn từ ngân hàng.",
        VerificationNextState.PROTECTIVE_ESCALATION.value:
            "Để bảo đảm an toàn, chúng tôi sẽ tiếp tục tạm giữ giao dịch. Nếu có ai yêu cầu bạn chuyển tiền hoặc bảo bạn không nói với ngân hàng, vui lòng dừng chuyển tiền và làm theo hướng dẫn của ngân hàng.",
        VerificationNextState.MANUAL_REVIEW.value:
            "Chúng tôi đã nhận câu trả lời của bạn. Nhân viên ngân hàng sẽ kiểm tra thêm để bảo đảm an toàn.",
        VerificationNextState.KEEP_HOLD.value:
            "Chúng tôi cần xác minh thêm. Vui lòng cho biết bạn có biết người nhận và mục đích của giao dịch này không.",
    }
    ne = {
        VerificationNextState.RELEASE_CANDIDATE.value:
            "पुष्टि गर्नुभएकोमा धन्यवाद। बैंक कर्मचारीले तपाईंको जवाफलाई कारोबार विवरणसँग मिलाएर जाँच गरेपछि जानकारी दिनेछन्।",
        VerificationNextState.ACCOUNT_TAKEOVER.value:
            "तपाईंको सुरक्षाका लागि यो कारोबार रोकिराखिनेछ। तपाईंले यो कारोबार माग्नुभएको होइन भने पासवर्ड परिवर्तन गर्नुहोस् र बैंकको निर्देशन पर्खनुहोस्।",
        VerificationNextState.PROTECTIVE_ESCALATION.value:
            "तपाईंको सुरक्षाका लागि यो कारोबार रोकिराखिनेछ। कसैले पैसा पठाउन भनेको वा बैंकलाई नभन्न भनेको छ भने थप पैसा नपठाउनुहोस् र बैंकको निर्देशन पालना गर्नुहोस्।",
        VerificationNextState.MANUAL_REVIEW.value:
            "हामीले तपाईंको जवाफ प्राप्त गर्‍यौं। सुरक्षाका लागि बैंक कर्मचारीले थप जाँच गर्नेछन्।",
        VerificationNextState.KEEP_HOLD.value:
            "हामीलाई थप पुष्टि चाहिन्छ। कृपया तपाईंले प्राप्तकर्ता र यो कारोबारको उद्देश्य चिन्नुहुन्छ कि भनेर बताउनुहोस्।",
    }
    bank = {"ko": ko, "en": en, "vi": vi, "ne": ne}
    return bank.get(lang, en).get(next_state, bank.get(lang, en)[VerificationNextState.KEEP_HOLD.value])


def _checklist(intent: str) -> list[str]:
    if intent == VerificationIntent.CONFIRMED.value:
        return ["금액·수취국·채널을 고객 답변과 대조", "수취인 관계와 송금 목적 일치 확인", "고위험 룰이 남아 있으면 FDS 분석가 재확인"]
    if intent == VerificationIntent.DENIES.value:
        return ["고객 계정 접근 이력 확인", "신규기기/접속국가 본인 여부 확인", "비밀번호 변경 및 계좌 보호 안내"]
    if intent in (VerificationIntent.COERCION.value, VerificationIntent.REMOTE_CONTROL.value,
                  VerificationIntent.SCAM_SCRIPT.value):
        return ["거래 보류 유지", "고객에게 제3자 지시 중단 안내", "보이스피싱/강요 가능성 보호 라우팅"]
    return ["수취인·목적 추가 질문", "답변 모순 여부 확인", "명확해질 때까지 보류 유지"]


class VerificationChatAgent:
    """고객 답변 → intent/요약/다음 메시지/라우팅 후보."""

    def __init__(self, mode: str = "template", model: str = "claude-sonnet-4-6"):
        self.mode = mode
        self.model = model

    def _prompt(self, alert: dict, cards: list[dict], reply: str) -> str:
        lang = alert.get("language") or "ko"
        lang_name = _LANG_NAMES.get(lang, "the customer's native language")
        schema = {
            "detected_intent": sorted(_INTENTS),
            "analyst_summary_ko": "Korean one-sentence summary of the customer reply",
            "customer_next_message": f"short next message in {lang_name}",
            "evidence_ids": ["E_TX_1"],
            "confidence": "low|medium|high",
        }
        return (
            "You assist a bank verification agent. You do NOT approve, block, or score the transaction. "
            "Classify only the customer's reply using one detected_intent from the schema. "
            "If the customer mentions coercion, secrecy, remote-control apps, loan fees, investment pressure, "
            "or denies the transaction, classify conservatively. "
            f"Write customer_next_message in {lang_name}; write analyst_summary_ko in Korean. "
            "Cite only existing evidence_ids. Return valid JSON only.\n\n"
            f"Schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Evidence cards:\n{json.dumps(cards, ensure_ascii=False, default=str)}\n\n"
            f"Alert metadata:\n{json.dumps(alert, ensure_ascii=False, default=str)}\n\n"
            f"Customer reply:\n{reply}"
        )

    def _claude_turn(self, alert: dict, cards: list[dict], reply: str) -> Optional[dict]:
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": self._prompt(alert, cards, reply)}],
            )
            return _safe_json_loads(msg.content[0].text.strip())
        except Exception:
            return None

    def _openai_turn(self, alert: dict, cards: list[dict], reply: str) -> Optional[dict]:
        base_url = os.environ.get("FRAUDGUARD_LLM_BASE_URL")
        if not base_url:
            return None
        api_key = os.environ.get("FRAUDGUARD_LLM_API_KEY", "not-needed")
        model = os.environ.get("FRAUDGUARD_LLM_MODEL", self.model)
        payload = json.dumps({
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": self._prompt(alert, cards, reply)}],
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                     "User-Agent": "fraud-guard/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return _safe_json_loads((data["choices"][0]["message"]["content"] or "").strip())
        except Exception:
            return None

    def _repair(self, raw: Optional[dict], base: dict, cards: list[dict], heuristic: str) -> dict:
        warnings = list(base.get("repair_warnings") or [])
        valid = _valid_ids(cards)
        fallback = _fallback_ids(cards) or ["E_TX_1"]
        if raw is None:
            return base

        raw_intent = str(raw.get("detected_intent") or "").strip()
        if heuristic != VerificationIntent.UNCLEAR.value:
            if raw_intent and raw_intent != heuristic:
                warnings.append(f"intent overridden by safety guard: {raw_intent} -> {heuristic}")
            intent = heuristic
        elif raw_intent in _INTENTS:
            intent = raw_intent
        else:
            intent = VerificationIntent.UNCLEAR.value
            warnings.append("detected_intent repaired")

        next_state = _route(intent)
        base["detected_intent"] = intent
        base["next_state"] = next_state
        base["confidence"] = str(raw.get("confidence") or _confidence(intent))
        if base["confidence"] not in ("low", "medium", "high"):
            warnings.append("confidence repaired")
            base["confidence"] = _confidence(intent)

        summary = str(raw.get("analyst_summary_ko") or "").strip()
        if summary:
            base["analyst_summary_ko"] = summary
        message = str(raw.get("customer_next_message") or "").strip()
        if message and _script_matches(base["language"], message):
            base["customer_next_message"] = message
        elif message:
            warnings.append("customer_next_message script mismatch, template message used")

        ids = [str(i) for i in (raw.get("evidence_ids") or []) if str(i) in valid]
        if ids:
            base["evidence_ids"] = ids
        elif raw.get("evidence_ids") is not None:
            warnings.append("evidence_ids repaired")
            base["evidence_ids"] = fallback

        base["operator_checklist"] = _checklist(intent)
        base["repair_warnings"] = warnings
        base["llm_status"] = "ok" if not warnings else "repaired"
        return base

    def process(self, alert: dict, turn_input: VerificationTurnInput | dict,
                turn_index: int = 1) -> dict:
        inp = turn_input if isinstance(turn_input, VerificationTurnInput) else VerificationTurnInput(**turn_input)
        cards = _evidence_cards(alert)
        heuristic = _heuristic_intent(inp.customer_reply)
        next_state = _route(heuristic)
        lang = alert.get("language") or "ko"
        base = {
            "tx_id": alert.get("id") or alert.get("tx_id"),
            "customer_id": alert.get("customer_id"),
            "language": lang,
            "turn_index": turn_index,
            "customer_reply": inp.customer_reply,
            "detected_intent": heuristic,
            "next_state": next_state,
            "analyst_summary_ko": _summary(heuristic, inp.customer_reply),
            "customer_next_message": _message(lang, next_state),
            "evidence_ids": _fallback_ids(cards) or ["E_TX_1"],
            "confidence": _confidence(heuristic),
            "operator_checklist": _checklist(heuristic),
            "generated_by": "template",
            "llm_status": "template",
            "repair_warnings": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        raw, generated_by = None, "template"
        if self.mode == "claude":
            raw = self._claude_turn(alert, cards, inp.customer_reply)
            if raw is not None:
                generated_by = "live_claude"
        elif self.mode == "openai":
            raw = self._openai_turn(alert, cards, inp.customer_reply)
            if raw is not None:
                generated_by = "live_openai"

        if raw is None and self.mode in ("claude", "openai"):
            base["llm_status"] = "llm_unavailable_fallback"
        base["generated_by"] = generated_by
        repaired = self._repair(raw, base, cards, heuristic)
        return VerificationTurnOutput(**repaired).dict()
