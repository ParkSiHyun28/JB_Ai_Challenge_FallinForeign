"""contracts/transaction_input.py — 금융/오케스트레이터 → 이상치팀 거래 경계 계약.

VisaInput 이 서류 경계를 검증하듯, TransactionInput 은 네트워크로 들어오는 거래
payload 를 core dataclass 로 넘기기 전에 검증·정규화한다. core 는 여전히 Pydantic 을
모르고, app_mcp.schemas.transaction_from_dict 가 이 계약을 통과한 값만 변환한다.

주의: 설치 환경은 pydantic v1(1.10.x) 이므로 v1 API(`validator`, `class Config`)로 작성.
"""
from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, validator


class TransactionChannel(str, Enum):
    """core.schema.Channel 리터럴과 값이 1:1."""

    DOMESTIC = "domestic"
    REMITTANCE = "remittance"
    ATM = "atm"


class TransactionInput(BaseModel):
    """거래 입력 계약. dict→TransactionInput 검증 통과 후 core.Transaction 으로 변환."""

    tx_id: str
    customer_id: str
    timestamp: float
    amount: float
    channel: TransactionChannel
    counterparty_country: str
    device_id: str
    ip_country: str
    balance_before: float = 0.0
    balance_drawdown_ratio: float = 0.0
    is_new_device: bool = False
    tx_velocity_24h: int = 0
    tz_offset_minutes: int = 540

    class Config:
        use_enum_values = True

    @validator("tx_id", "customer_id", "counterparty_country", "device_id", "ip_country")
    def _not_blank(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must not be blank")
        return str(v).strip()

    @validator("counterparty_country", "ip_country")
    def _country_upper(cls, v: str) -> str:
        return v.upper()

    @validator("timestamp", "amount", "balance_before", "balance_drawdown_ratio")
    def _finite(cls, v: float) -> float:
        value = float(v)
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @validator("amount", "balance_before")
    def _non_negative_money(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be non-negative")
        return v

    @validator("balance_drawdown_ratio")
    def _unit_interval(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("must be between 0 and 1")
        return v

    @validator("tx_velocity_24h")
    def _non_negative_velocity(cls, v: int) -> int:
        value = int(v)
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @validator("tz_offset_minutes")
    def _reasonable_tz_offset(cls, v: int) -> int:
        value = int(v)
        if not (-14 * 60 <= value <= 14 * 60):
            raise ValueError("must be a valid UTC offset in minutes")
        return value
