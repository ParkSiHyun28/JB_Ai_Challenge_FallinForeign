"""contracts/alert_output.py — 이상치팀(fraud-guard) → 오케스트레이터 경계 계약.

CLAUDE.md 출력 경계: 탐지 결과를 오케스트레이터에 넘기는 **형식을 여기서 정의**한다
(입력 경계 contracts/visa_input.py 와 대칭). 입력만 Pydantic 으로 검증하고 출력은
임시 dict 로 흘리면 팀 간 인터페이스가 코드로 고정되지 않으므로, 출력도 계약을 둔다.

불변원칙 2(core 는 MCP/계약을 모른다): core 는 이 모델을 import 하지 않는다. 경계 변환을
담당하는 app_mcp/schemas.result_to_dict 가 이 모델로 출력을 **검증·정규화**한다.

주의: 설치 환경은 pydantic v1(1.10.x) → v1 API(validator, class Config)로 작성.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, validator


class AlertAction(str, Enum):
    """결정 레벨(오름차순 심각도). core.schema.Action 리터럴과 값이 1:1."""

    ALLOW = "allow"
    REVIEW = "review"
    SOFT_BLOCK = "soft_block"


class AlertOutput(BaseModel):
    """탐지 1건 결과 — score_transaction / detect_account_takeover 표준 출력.

    risk_score 주의: 두 축(룰=페널티공간 vs IF=분위공간)의 **표시용 집계**(max)다.
    스케일이 다르므로 축을 가로지르는 절대 비교/우선순위에 직접 쓰지 말 것 —
    결정은 action 으로 이미 끝났다(분위수는 모델축 FPR 만 통제).
    """

    tx_id: str
    rule_score: float             # 0~1, 룰 페널티 누적(캡 1.0)
    model_score: Optional[float]  # 0~1, IF 분위. 미학습 그룹은 None(센티넬 -1.0 금지, P1-6)
    risk_score: float             # 0~1, 표시용 집계(축 간 절대비교 불가)
    triggered_rules: List[str] = []
    action: AlertAction           # allow < review < soft_block
    explanation: dict = {}        # axes / features / explain_method / takeover_boost 등

    class Config:
        # core 는 enum 을 모름 → 통과 후 .action 은 "soft_block" 같은 문자열로 노출.
        use_enum_values = True

    @validator("rule_score", "risk_score")
    def _unit_interval(cls, v: float) -> float:
        if not (0.0 <= float(v) <= 1.0):
            raise ValueError(f"점수는 0~1 범위여야 함 (got {v})")
        return float(v)

    @validator("model_score")
    def _unit_or_none(cls, v):
        if v is not None and not (0.0 <= float(v) <= 1.0):
            raise ValueError(f"model_score 는 0~1 또는 None 이어야 함 (got {v})")
        return None if v is None else float(v)


if __name__ == "__main__":
    # 통과/실패 데모 (입력 계약 visa_input 과 동일한 자기검증 패턴)
    ok = AlertOutput(tx_id="t1", rule_score=0.45, model_score=0.991, risk_score=0.991,
                     triggered_rules=["corridor_mismatch"], action="soft_block",
                     explanation={"axes": {"rule_action": "review", "model_action": "soft_block"}})
    print("[PASS]", ok.dict())

    none_ok = AlertOutput(tx_id="t2", rule_score=0.0, model_score=None, risk_score=0.0, action="allow")
    print("[PASS model_score=None]", none_ok.model_score is None)

    for bad in (
        {"tx_id": "x", "rule_score": 1.5, "model_score": 0.1, "risk_score": 0.1, "action": "allow"},
        {"tx_id": "y", "rule_score": 0.1, "model_score": 0.1, "risk_score": 0.1, "action": "freeze"},
    ):
        try:
            AlertOutput(**bad)
            print("[UNEXPECTED PASS]", bad)
        except Exception as e:
            print("[FAIL as expected]", type(e).__name__)
