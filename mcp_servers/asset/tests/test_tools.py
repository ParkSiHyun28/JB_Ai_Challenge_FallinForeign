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


# ---------------------------------------------------------------------------
# 연금: 공단 공식(납부보험료+이자) + 국가 테이블 판정 (2026-07 고도화)
# ---------------------------------------------------------------------------

def test_pension_estimator_minh_e9_special_can_receive():
    """민(베트남 E-9): 국적 기준은 보류국이지만 E-9 특례로 수령 가능해야 한다."""
    result = tools.pension_estimator(persona_id="minh")
    n = result["numbers"]
    assert n["eligible"] is True
    assert n["basis"] == "visa_special"
    assert result["card"] is not None
    # 시효는 출국 사유 5년이 표기돼야 한다
    assert "5년" in result["detail"]


def test_pension_estimator_minh_principal_follows_yearly_rate():
    """원금 = 월급 × 연도별 요율 합. 민: 2022-08부터 50개월
    → 2025년까지 41개월 9% + 2026년 9개월 9.5%."""
    from shared.personas import get_persona
    p = get_persona("minh")
    wage = p["monthly_wage_krw"]
    expected_principal = int(round(wage * (0.09 * 41 + 0.095 * 9)))
    result = tools.pension_estimator(persona_id="minh")
    n = result["numbers"]
    assert n["principal_krw"] == expected_principal
    assert n["interest_krw"] > 0
    assert n["estimated_refund_krw"] == n["principal_krw"] + n["interest_krw"]


def test_pension_estimator_suman_not_enrolled_honest():
    """수만(네팔): 가입 제외국이라 반환일시금 자체가 해당 없음을 정직하게 안내한다.
    옛 '취업전환하면 수령 가능' 오류 안내가 나오면 안 된다."""
    result = tools.pension_estimator(persona_id="suman")
    n = result["numbers"]
    assert n["eligible"] is False
    assert n["reason"] == "not_enrolled"
    assert "가입 대상이 아닙" in result["detail"]
    assert "취업" not in result["detail"] or "취업전환" not in result["detail"]
    assert result["card"] is None


def test_pension_estimator_unknown_country_holds_judgement():
    """판정 테이블에 없는 국가는 추측하지 않고 보류를 안내한다."""
    from shared.personas import register_personas
    register_personas({
        "test_unknown_xx": {
            "id": "test_unknown_xx", "name": "테스트", "name_en": "Test", "flag": "XX",
            "country": "미등록국", "visa": "E-9", "role": "근로자",
            "entry_date": "2024-01", "exit_plan": "2027-06",
            "monthly_wage_krw": 2_500_000, "monthly_remit_krw": 0, "pension_months": 20,
            "social_security_treaty": False, "deposit_balance_krw": 0,
            "remit_route": None, "credit_accrual_start": None, "summary": "테스트",
        }
    })
    result = tools.pension_estimator(persona_id="test_unknown_xx")
    assert result["numbers"]["eligible"] is None
    assert result["numbers"]["reason"] == "unknown_country"
    assert result["card"] is None


# ---------------------------------------------------------------------------
# 송금: 총비용(고정수수료+환율마진) 비교 + 귀국 전 총 절감 (2026-07 고도화)
# ---------------------------------------------------------------------------

def test_remit_optimizer_minh_total_cost_comparison():
    """민: 월 100만 송금. 은행 창구(현재) 월 5.5만 → 소액송금업체 월 1만.
    매달 4.5만 절감. 귀국(2027-01)까지 3개월 → 총 13.5만."""
    result = tools.remit_optimizer(persona_id="minh")
    n = result["numbers"]
    assert n["current_route"] == "bank_counter"
    assert n["current_cost_krw"] == 18_000 + 27_000 + 10_000   # 고정+중계+마진 1%
    assert n["best_route"] == "fintech"
    assert n["best_cost_krw"] == 4_000 + 6_000                  # 고정+마진 0.6%
    assert n["monthly_saving_krw"] == 45_000
    assert n["months_to_exit"] == 3                             # 2026-10 → 2027-01
    assert n["total_saving_until_exit_krw"] == 135_000
    assert result["card"] is not None


def test_remit_optimizer_suman_no_remit_returns_none_card():
    result = tools.remit_optimizer(persona_id="suman")
    # 수만은 월 송금 0 → 비교 의미 없음, card None
    assert result["card"] is None


def test_remit_optimizer_already_best_route():
    """이미 최저 경로를 쓰는 사람에겐 '이미 최적'을 안내한다(절감액 강요 금지)."""
    from shared.personas import register_personas
    register_personas({
        "test_best_route": {
            "id": "test_best_route", "name": "테스트2", "name_en": "Test2", "flag": "VN",
            "country": "베트남", "visa": "E-9", "role": "근로자",
            "entry_date": "2024-01", "exit_plan": "2027-06",
            "monthly_wage_krw": 2_500_000, "monthly_remit_krw": 1_000_000, "pension_months": 20,
            "social_security_treaty": False, "deposit_balance_krw": 0,
            "remit_route": "fintech", "credit_accrual_start": None, "summary": "테스트",
        }
    })
    result = tools.remit_optimizer(persona_id="test_best_route")
    assert result["numbers"]["monthly_saving_krw"] == 0
    assert "이미" in result["summary"]
    assert result["card"] is not None


# ---------------------------------------------------------------------------
# 신용: credit_accrual_start 필드 기반 계산 + KCB 12/36 사다리 (2026-07 고도화)
# ---------------------------------------------------------------------------

def test_credit_builder_suman_months_from_persona_field():
    """수만: 2024-03 시작 → 기준일 2026-10 = 31개월. 고정값(옛 8개월) 금지."""
    result = tools.credit_builder(persona_id="suman")
    n = result["numbers"]
    assert n["months_accrued"] == 31
    assert n["reached_min"] is True      # 12개월 통과
    assert n["reached_max"] is False     # 36개월 미달
    assert n["months_to_next"] == 5
    assert n["next_step_ym"] == "2027-03"
    assert result["card"] is not None


def test_credit_builder_minh_not_started():
    """민: credit_accrual_start=None → 축적 0. 시작 안내."""
    result = tools.credit_builder(persona_id="minh")
    n = result["numbers"]
    assert n["months_accrued"] == 0
    assert n["reached_min"] is False
    assert result["card"] is not None


def test_credit_builder_ladder_uses_verified_kcb_constants():
    """사다리 기준이 KCB 확인치(12/36)여야 한다. 근거 없는 옛 6/18 회귀 방지."""
    result = tools.credit_builder(persona_id="suman")
    assert result["numbers"]["min_months"] == 12
    assert result["numbers"]["max_months"] == 36


# ---------------------------------------------------------------------------
# 마감 D-Day (기존 동작 유지)
# ---------------------------------------------------------------------------

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
