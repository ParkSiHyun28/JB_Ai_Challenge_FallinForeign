"""contracts/investigation_output.py — AI 조사관 출력 계약.

LLM 출력은 외부 입력처럼 strict reject 하지 않는다. agent.investigate 가 원문을 관대하게
복구한 뒤, 최종 산출물이 이 계약을 통과하게 만든다. 즉 이 모델은 "Claude 원문" 검증기가
아니라 오케스트레이터/콘솔에 넘기는 **복구 완료 조사관 리포트** 계약이다.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, validator


class GeneratedBy(str, Enum):
    TEMPLATE = "template"
    LIVE_CLAUDE = "live_claude"
    CACHED_CLAUDE = "cached_claude"
    LIVE_OPENAI = "live_openai"


class EvidenceCard(BaseModel):
    """코드가 만든 원증거 카드. LLM 은 id 를 참조만 한다."""

    id: str
    kind: str
    title: str
    fact: str
    value: Optional[str] = None
    source: str

    @validator("id", "kind", "title", "fact", "source")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()


class InvestigationQuestion(BaseModel):
    """확정/반증을 위한 다음 확인 질문. 조사관 harness 의 주역."""

    id: str
    question: str
    purpose: str
    evidence_ids: List[str]

    @validator("id", "question", "purpose")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()


class InvestigationHypothesis(BaseModel):
    """가설은 단정이 아니라 evidence_ids 에 묶인 낮은 확신 후보로만 둔다."""

    name: str
    status: str = "hypothesis"
    confidence: str = "low"
    supporting_evidence_ids: List[str]
    source: str = "code"  # "code"=결정론 코드 소유, "llm_suggested"=LLM 비권위 소견(B 플래그)

    @validator("name")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()

    @validator("confidence")
    def _confidence(cls, v: str) -> str:
        return v if v in ("low", "medium", "high") else "low"


class InvestigationOutput(BaseModel):
    """보류/검토 거래 1건에 대한 근거 기반 조사관 리포트."""

    tx_id: str
    customer_id: Optional[str] = None
    case_summary: str
    risk_narrative: str  # 하위호환: case_summary 와 같은 결정론 요약
    key_evidence: List[EvidenceCard]
    hypotheses: List[InvestigationHypothesis]  # 항상 코드 소유(suspected_type 기반). LLM 미개입.
    # B 플래그(reveal_llm_opinion)일 때만 채워지는 LLM 비권위 소견. hypotheses 와 스키마상 분리 →
    # 소비자가 "코드 단정"과 "LLM 제안"을 이름으로 구분(배지 무시해도 혼동 불가). 기본 [].
    llm_suggested_hypotheses: List[InvestigationHypothesis] = []
    verification_questions: List[InvestigationQuestion]
    recommended_next_action: str
    confidence: str
    evidence: dict
    evidence_hash: str
    generated_by: GeneratedBy
    llm_status: str
    repair_warnings: List[str] = []

    # 별칭 필드(현 소비자 명시): suspected_type=게이트웨이 `/alert/{id}/investigate` 응답(mcp_http_gateway.py),
    # recommended_action/needed_checks=기존 테스트·대시보드 v1. 신규 UI 는 hypotheses/verification_questions·
    # recommended_next_action 을 정본으로 쓴다. (suspected_type 은 코드 _suspected_type 만 채움 — LLM 미개입.)
    suspected_type: str
    recommended_action: str
    needed_checks: List[str]

    class Config:
        use_enum_values = True

    @validator("tx_id", "case_summary", "risk_narrative", "recommended_next_action",
               "confidence", "evidence_hash", "llm_status", "suspected_type",
               "recommended_action")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()

    @validator("confidence")
    def _confidence(cls, v: str) -> str:
        return v if v in ("low", "medium", "high") else "low"
