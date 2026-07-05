"""verification_agent/case.py — 보류 거래 컨텍스트 + conclude 도구.

VerificationCase 는 에이전트가 대화 근거로 삼는 거래 사실(금액·수취국·발동룰 등)과,
마지막 conclude_verification 결과 홀더를 담는다. 판정은 담지 않는다(그건 사람 몫).

intent/next_state enum 값은 contracts/verification_chat 과 1:1 로 맞춘다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# contracts/verification_chat.VerificationIntent 와 동일 값
_INTENTS = [
    "confirmed_by_customer", "denies_transaction", "coercion_hint",
    "remote_control_hint", "scam_script_hint", "inconsistent_confirmation",
    "unclear_needs_followup", "unsafe_or_irrelevant_reply",
]
# contracts/verification_chat.VerificationNextState 와 동일 값
_NEXT_STATES = [
    "release_candidate", "account_takeover_escalation", "protective_escalation",
    "keep_hold_and_ask_followup", "manual_review",
]


@dataclass
class VerificationCase:
    """대화 근거가 되는 보류 거래 사실 + conclude 결과 홀더."""

    tx_id: str
    customer_id: str
    language: str                 # "vi" / "ne" ...
    amount: float
    counterparty_country: str
    channel: str
    triggered_rules: list[str]
    hold_reason_ko: str           # 왜 보류됐는지(분석가가 준 한국어 컨텍스트)
    concluded: Optional[dict] = None

    @classmethod
    def from_alert(cls, alert: dict) -> "VerificationCase":
        """게이트웨이 알림 dict → 본인확인 대화 케이스."""
        rules = list(alert.get("triggered_rules") or [])
        reason = (f"{alert.get('action', 'held')} — 발동 신호: {', '.join(rules) or '없음'}"
                  f" (제3국/출국기/신규기기 등 위험 패턴)")
        return cls(
            tx_id=alert.get("id", "?"),
            customer_id=alert.get("customer_id", "?"),
            language=alert.get("language", "ko"),
            amount=float(alert.get("amount", 0) or 0),
            counterparty_country=alert.get("counterparty_country", "-"),
            channel=alert.get("channel", "-"),
            triggered_rules=rules,
            hold_reason_ko=reason,
        )

    def facts_for_prompt(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "amount_krw": self.amount,
            "counterparty_country": self.counterparty_country,
            "channel": self.channel,
            "triggered_rules": self.triggered_rules,
            "hold_reason_ko": self.hold_reason_ko,
            "customer_language": self.language,
        }

    # --- 도구 실행 ---
    def run(self, name: str, args: dict) -> dict:
        if name != "conclude_verification":
            return {"error": f"unknown tool '{name}'"}
        intent = args.get("detected_intent")
        nxt = args.get("next_state")
        self.concluded = {
            "detected_intent": intent if intent in _INTENTS else "unclear_needs_followup",
            "next_state": nxt if nxt in _NEXT_STATES else "manual_review",
            "analyst_summary_ko": str(args.get("analyst_summary_ko", "")).strip(),
            "closing_message_native": str(args.get("closing_message_native", "")).strip(),
            "operator_checklist": [str(x).strip() for x in (args.get("operator_checklist") or [])
                                   if str(x).strip()][:6],
            "confidence": args.get("confidence") if args.get("confidence") in
            ("low", "medium", "high") else "low",
        }
        note = ("결론 기록됨. 판정(승인/차단)은 사람 몫 — next_state 는 라우팅 후보일 뿐. "
                "대화를 마무리하라.")
        if self.concluded["next_state"] in ("protective_escalation", "account_takeover_escalation"):
            note += " 위험 신호가 감지됐으니 고객에게 승인을 유도하지 말 것."
        return {"status": "recorded", "note": note}


# --- Anthropic tool 스키마 ---
CONCLUDE_TOOL: dict = {
    "name": "conclude_verification",
    "description": (
        "고객 답변에서 충분한 신호(본인확인/거부/강요·원격제어·피싱스크립트)를 얻으면 "
        "이 도구로 분석가용 구조화 인계를 만들고 대화를 끝낸다. "
        "너는 승인/차단을 결정하지 않는다 — next_state 는 사람이 볼 라우팅 후보다."),
    "input_schema": {
        "type": "object",
        "properties": {
            "detected_intent": {"type": "string", "enum": _INTENTS,
                                "description": "고객 답변에서 읽은 신호"},
            "next_state": {"type": "string", "enum": _NEXT_STATES,
                           "description": "사람이 볼 운영 라우팅 후보(자동 승인/차단 아님)"},
            "analyst_summary_ko": {"type": "string",
                                   "description": "분석가용 한국어 요약(무슨 신호를 왜 봤는지)"},
            "closing_message_native": {"type": "string",
                                       "description": "고객에게 보낼 마무리 멘트(고객 모국어)"},
            "operator_checklist": {"type": "array", "items": {"type": "string"},
                                   "description": "상담사/분석가가 다음에 확인할 점검(한국어)"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["detected_intent", "next_state", "analyst_summary_ko",
                     "closing_message_native", "confidence"],
    },
}
