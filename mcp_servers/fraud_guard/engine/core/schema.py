"""core/schema.py — fraud-guard 공통 데이터 타입 (단일 정의처).

합성생성·룰·베이스라인·결정·설명 등 모든 계층이 import 하는 기반 타입.
불변 원칙 2(core는 MCP를 모른다)에 따라 mcp / pydantic 의존성을 두지 않는다.
서버 없이 `pytest` 가 돌아야 하므로 순수 dataclass 로만 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

# 채널·액션은 문자열 리터럴로 고정(오타 방지 + IDE 보조). core 외부에서도 동일 값 사용.
Channel = Literal["domestic", "remittance", "atm"]
Action = Literal["allow", "review", "soft_block"]

# 헌법 결정사항(P0-1): hour 피처/야간룰은 **거래 발생지(고객) 로컬시각** 기준이다.
# epoch→hour 를 UTC 로 뽑으면 KST 09:00 이 hour=0(야간)으로 오탐된다. 모집단이
# 재한 외국인이므로 기본 오프셋은 KST(UTC+9)=540분. 실데이터는 거래별로 다른
# 오프셋을 Transaction.tz_offset_minutes 에 주입할 수 있다(공항/타지 거래 등).
KST_OFFSET_MINUTES: int = 540


@dataclass
class CustomerProfile:
    """고객 메타데이터. 비자 만료일·체류자격은 서류팀 OCR → contracts/visa_input 으로 수신."""

    customer_id: str
    nationality: str          # 국가코드: "VN", "NP" ...
    visa_type: str            # "E-9", "D-2" ...
    residency_end_date: date  # 체류 만료일
    language: str             # "vi", "ne" — 모국어 본인확인(L4)에 사용
    home_country: str         # corridor 정상 송금 대상국("VN" 등)

    @property
    def segment_key(self) -> str:
        """(국적 × 비자) 클러스터 키 — L2 BaselineStore 그룹 식별자."""
        return f"{self.nationality}:{self.visa_type}"


@dataclass
class Transaction:
    """거래 1건. 행동 컨텍스트(인출률·velocity 등)는 직전 상태에서 계산해 주입한다."""

    tx_id: str
    customer_id: str
    timestamp: float          # epoch seconds
    amount: float             # KRW
    channel: Channel          # "domestic" | "remittance" | "atm"
    counterparty_country: str  # 수취/상대 국가코드
    device_id: str
    ip_country: str
    balance_before: float = 0.0
    balance_drawdown_ratio: float = 0.0  # 이번 거래로 빠진 잔액 비율 0~1
    is_new_device: bool = False
    tx_velocity_24h: int = 0             # 최근 24h 내 거래 수
    tz_offset_minutes: int = KST_OFFSET_MINUTES  # hour 산출 로컬시각 오프셋(기본 KST)


@dataclass
class ScoreResult:
    """L3 DecisionEngine 출력. explanation 은 보류(soft_block) 거래에만 채워진다."""

    tx_id: str
    rule_score: float
    model_score: Optional[float]  # 0~1(높을수록 이상). 미학습 그룹은 None(P1-6: 센티넬 -1.0 폐기)
    risk_score: float         # 0~1, 결합 점수
    triggered_rules: list[str] = field(default_factory=list)
    action: Action = "allow"  # "allow" | "review" | "soft_block"
    explanation: dict = field(default_factory=dict)  # SHAP/DIFFI 기여도
