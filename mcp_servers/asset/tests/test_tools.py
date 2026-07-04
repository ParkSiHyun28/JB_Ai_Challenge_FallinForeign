from mcp_servers.asset import tools
from mcp_servers.asset import data


def test_collateral_calc_suman_returns_95_percent_limit():
    result = tools.collateral_calc(persona_id="suman")
    # 수만 잔고 2,000만 원의 95% = 1,900만 원
    assert result["numbers"]["loan_limit_krw"] == 19_000_000
    assert result["numbers"]["deposit_krw"] == 20_000_000
    assert "summary" in result
    assert "detail" in result
    assert result["card"] is not None
    assert set(result["card"].keys()) == {"icon", "head", "body", "metric"}


def test_collateral_calc_minh_has_no_deposit():
    result = tools.collateral_calc(persona_id="minh")
    # 민은 잔고 0 → 한도 0, card는 None (담보 없음)
    assert result["numbers"]["loan_limit_krw"] == 0
    assert result["card"] is None


def test_pension_estimator_minh_treaty_false_can_receive():
    from shared.personas import get_persona
    result = tools.pension_estimator(persona_id="minh")
    # 베트남 미체결 → 수령 가능. 반환일시금 = 납부월수 * 월환산액.
    # 납부월수는 페르소나 데이터에서 읽어 데이터 변경에 안 깨지게 한다.
    months = get_persona("minh")["pension_months"]
    assert result["numbers"]["can_receive"] is True
    assert result["numbers"]["estimated_refund_krw"] == months * data.PENSION_MONTHLY_REFUND_KRW
    assert result["card"] is not None


def test_pension_estimator_suman_treaty_false_cannot_receive():
    result = tools.pension_estimator(persona_id="suman")
    # 네팔 미체결 + 유학생(납부 0개월) → 귀국 시 수령 불가, 정직 안내
    assert result["numbers"]["can_receive"] is False
    assert result["card"] is not None  # 정직 안내 카드는 띄운다


def test_remit_optimizer_minh_finds_cheapest_route():
    result = tools.remit_optimizer(persona_id="minh")
    # 월 송금 100만 원. 최저 경로는 WireBarley(1.6%).
    assert result["numbers"]["best_route"] == "WireBarley"
    assert result["numbers"]["best_fee_rate"] == data.REMIT_FEE_ALT
    # 절감액 = (5.15% - 1.6%) * 100만 = 35,500원
    assert result["numbers"]["monthly_saving_krw"] == 35_500
    assert result["card"] is not None


def test_remit_optimizer_suman_no_remit_returns_none_card():
    result = tools.remit_optimizer(persona_id="suman")
    # 수만은 월 송금 0 → 비교 의미 없음, card None
    assert result["card"] is None


def test_credit_builder_suman_thin_filer_starts_accrual():
    result = tools.credit_builder(persona_id="suman", months_accrued=18)
    # 18개월 = 완성 기준 도달
    assert result["numbers"]["months_accrued"] == 18
    assert result["numbers"]["profile_complete"] is True
    assert result["card"] is not None


def test_credit_builder_below_minimum_not_complete():
    result = tools.credit_builder(persona_id="suman", months_accrued=3)
    # 3개월 = 최소(6) 미달
    assert result["numbers"]["profile_complete"] is False
    assert result["numbers"]["profile_started"] is False


def test_deadline_radar_minh_computes_days_to_exit():
    # 기준일 2026-10-03, 출국 2027-01 → 약 D-90
    result = tools.deadline_radar(persona_id="minh", as_of="2026-10-03")
    assert result["numbers"]["days_to_exit"] > 0
    assert result["numbers"]["has_severance_insurance"] is True
    assert result["card"] is not None


def test_deadline_radar_suman_no_severance_insurance():
    result = tools.deadline_radar(persona_id="suman", as_of="2026-10-03")
    # 유학생은 출국만기보험 대상 아님
    assert result["numbers"]["has_severance_insurance"] is False


def test_every_tool_has_schema():
    from mcp_servers.asset import schemas
    from mcp_servers.asset.tools import TOOL_REGISTRY
    for name in TOOL_REGISTRY:
        assert name in schemas.TOOL_SCHEMAS, f"{name} 스키마 누락"
        s = schemas.TOOL_SCHEMAS[name]
        assert s["name"] == name
        assert "description" in s
        assert s["input_schema"]["type"] == "object"
