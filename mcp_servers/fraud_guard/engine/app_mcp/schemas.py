"""app_mcp/schemas.py — MCP dict ↔ core 객체 변환 (얇은 경계).

서류팀에서 오는 비자 입력은 경계 계약 contracts.VisaInput 으로 **검증·정규화**한 뒤
core 타입으로 만든다(visa_type enum 검증, 국가코드 대문자, 날짜 파싱).
mcp 의존 없음 — 순수 변환이라 단위 테스트가 서버 없이 돈다.
"""
from __future__ import annotations

from datetime import date

from contracts.alert_output import AlertOutput
from contracts.transaction_input import TransactionInput
from contracts.visa_input import VisaInput
from core.schema import CustomerProfile, ScoreResult, Transaction


def profile_from_dict(d: dict) -> CustomerProfile:
    """프로필 dict → CustomerProfile. 비자 부분은 VisaInput 계약으로 검증."""
    vi = VisaInput(  # 통과 못 하면 여기서 ValidationError (경계에서 차단)
        customer_id=d["customer_id"], visa_type=d["visa_type"],
        residency_end_date=d["residency_end_date"], nationality=d["nationality"],
    )
    res_end = vi.residency_end_date
    if not isinstance(res_end, date):
        res_end = date.fromisoformat(str(res_end))
    return CustomerProfile(
        customer_id=vi.customer_id, nationality=vi.nationality, visa_type=vi.visa_type,
        residency_end_date=res_end, language=str(d["language"]),
        home_country=str(d["home_country"]).upper(),
    )


def transaction_from_dict(d: dict) -> Transaction:
    """거래 dict → Transaction. TransactionInput 계약으로 검증·정규화 후 변환."""
    ti = TransactionInput(**d)  # bool 문자열·범위·channel enum·국가코드 정규화는 여기서 처리
    return Transaction(
        tx_id=ti.tx_id,
        customer_id=ti.customer_id,
        timestamp=ti.timestamp,
        amount=ti.amount,
        channel=ti.channel,
        counterparty_country=ti.counterparty_country,
        device_id=ti.device_id,
        ip_country=ti.ip_country,
        balance_before=ti.balance_before,
        balance_drawdown_ratio=ti.balance_drawdown_ratio,
        is_new_device=ti.is_new_device,
        tx_velocity_24h=ti.tx_velocity_24h,
        tz_offset_minutes=ti.tz_offset_minutes,
    )


def assert_same_customer(tx: Transaction, profile: CustomerProfile) -> None:
    """거래와 비자/프로필 customer_id 가 같은 고객인지 경계에서 확인."""
    if tx.customer_id != profile.customer_id:
        raise ValueError(f"customer_id mismatch: transaction={tx.customer_id!r}, profile={profile.customer_id!r}")


def result_to_dict(r: ScoreResult) -> dict:
    """ScoreResult → 출력 경계 계약(AlertOutput)으로 검증·정규화한 dict (오케스트레이터로 반환).

    입력(VisaInput)과 대칭으로 출력도 계약을 통과시킨다 — 경계에서 형식(필드·범위·action
    값)을 보장한다(CLAUDE.md '출력 계약은 내가 정의'). core 는 계약을 모르고, 변환은 여기서만.
    """
    return AlertOutput(
        tx_id=r.tx_id,
        rule_score=r.rule_score,
        model_score=r.model_score,
        risk_score=r.risk_score,
        triggered_rules=list(r.triggered_rules),
        action=r.action,
        explanation=r.explanation,
    ).dict()
