"""contracts/verification_chat.py — 모국어 본인확인 대화 턴 계약.

`request_verification` 이 1회성 발송 메시지를 만든다면, 이 계약은 고객 답변 1턴을
받아 분석가가 읽을 수 있는 구조화 결과로 바꾸는 경계다. LLM 원문은 agent 에서
관대하게 repair 하고, 오케스트레이터/콘솔에는 이 최종 계약만 노출한다.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class VerificationIntent(str, Enum):
    """고객 답변에서 읽은 상담 신호. 금융 최종판정이 아니라 대화 분류다."""

    CONFIRMED = "confirmed_by_customer"
    DENIES = "denies_transaction"
    COERCION = "coercion_hint"
    REMOTE_CONTROL = "remote_control_hint"
    SCAM_SCRIPT = "scam_script_hint"
    INCONSISTENT = "inconsistent_confirmation"
    UNCLEAR = "unclear_needs_followup"
    UNSAFE = "unsafe_or_irrelevant_reply"


class VerificationNextState(str, Enum):
    """분류 결과를 사람이 볼 운영 라우팅 후보. 자동 승인/차단이 아니다."""

    RELEASE_CANDIDATE = "release_candidate"
    ACCOUNT_TAKEOVER = "account_takeover_escalation"
    PROTECTIVE_ESCALATION = "protective_escalation"
    KEEP_HOLD = "keep_hold_and_ask_followup"
    MANUAL_REVIEW = "manual_review"


class VerificationTurnInput(BaseModel):
    """콘솔/오케스트레이터가 고객 답변 1턴을 제출할 때의 입력 계약."""

    customer_reply: str
    selected_question_id: Optional[str] = None
    operator_id: Optional[str] = None
    channel: str = "simulated_chat"

    @validator("customer_reply")
    def _reply_not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("customer_reply must not be blank")
        value = str(v).strip()
        if len(value) > 2000:
            raise ValueError("customer_reply is too long")
        return value

    @validator("selected_question_id", "operator_id", pre=True, always=True)
    def _optional_strip(cls, v):
        if v is None:
            return None
        value = str(v).strip()
        return value or None

    @validator("channel")
    def _channel_not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("channel must not be blank")
        return str(v).strip()


class VerificationTurnOutput(BaseModel):
    """고객 답변 1턴의 구조화 결과."""

    tx_id: str
    customer_id: Optional[str] = None
    language: str
    turn_index: int = 1
    customer_reply: str
    detected_intent: VerificationIntent
    next_state: VerificationNextState
    analyst_summary_ko: str
    customer_next_message: str
    evidence_ids: List[str]
    confidence: str
    operator_checklist: List[str] = Field(default_factory=list)
    generated_by: str
    llm_status: str
    repair_warnings: List[str] = Field(default_factory=list)
    created_at: str

    class Config:
        use_enum_values = True

    @validator("tx_id", "language", "customer_reply", "analyst_summary_ko",
               "customer_next_message", "confidence", "generated_by",
               "llm_status", "created_at")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()

    @validator("turn_index")
    def _positive_turn(cls, v: int) -> int:
        value = int(v)
        if value < 1:
            raise ValueError("turn_index must be positive")
        return value

    @validator("confidence")
    def _confidence(cls, v: str) -> str:
        return v if v in ("low", "medium", "high") else "low"
