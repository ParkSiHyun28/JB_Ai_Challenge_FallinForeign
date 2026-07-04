from mcp_servers.docs import tools
from mcp_servers.docs import data


# --- perception_parse ---

def test_perception_parse_minh_alien_registration_returns_correct_fields():
    result = tools.perception_parse(persona_id="minh", doc_type="alien_registration")
    assert result["numbers"]["field_count"] == data.DOC_TYPES["alien_registration"]["field_count"]
    assert result["numbers"]["name_matched"] is True
    assert result["numbers"]["confidence"] == data.OCR_CONFIDENCE_BASE
    assert "summary" in result
    assert "detail" in result
    assert result["card"] is not None
    assert set(result["card"].keys()) == {"icon", "head", "body", "metric"}


def test_perception_parse_suman_passport():
    result = tools.perception_parse(persona_id="suman", doc_type="passport")
    assert result["numbers"]["field_count"] == data.DOC_TYPES["passport"]["field_count"]
    assert result["numbers"]["name_matched"] is True
    assert result["card"] is not None


def test_perception_parse_invalid_doc_type_returns_none_card():
    result = tools.perception_parse(persona_id="minh", doc_type="invalid_doc")
    assert result["numbers"]["field_count"] == 0
    assert result["card"] is None


def test_perception_parse_default_doc_type_works():
    # doc_type 생략 시 기본값(alien_registration)으로 동작해야 한다
    result = tools.perception_parse(persona_id="suman")
    assert result["numbers"]["doc_type"] == "alien_registration"
    assert result["card"] is not None


# --- compliance_reason ---

def test_compliance_reason_minh_jeonse_fraud_has_risk():
    result = tools.compliance_reason(persona_id="minh", check_type="jeonse_fraud")
    # E-9 근로자는 전세계약 위험 대상
    assert result["numbers"]["has_lease_risk"] is True
    assert result["numbers"]["risk_indicator_count"] == len(data.JEONSE_FRAUD_INDICATORS)
    assert result["numbers"]["jeonse_ratio_danger"] == data.JEONSE_RATIO_DANGER
    assert result["card"] is not None


def test_compliance_reason_suman_jeonse_fraud_not_applicable():
    result = tools.compliance_reason(persona_id="suman", check_type="jeonse_fraud")
    # D-2 유학생은 전세계약 해당 없음
    assert result["numbers"]["has_lease_risk"] is False
    assert result["numbers"]["risk_level"] == "해당없음"
    assert result["card"] is None  # 해당 없으면 card None


def test_compliance_reason_minh_visa_work_eligibility():
    result = tools.compliance_reason(persona_id="minh", check_type="visa_work_eligibility")
    # E-9: 지정 사업장 한정, 시간 제한 없음(None)
    assert result["numbers"]["weekly_limit_hours"] is None
    assert result["numbers"]["violation_risk"] is True
    assert result["card"] is not None


def test_compliance_reason_suman_visa_work_eligibility():
    result = tools.compliance_reason(persona_id="suman", check_type="visa_work_eligibility")
    # D-2: 주 20시간 이내
    assert result["numbers"]["weekly_limit_hours"] == data.VISA_WORK_LIMITS["D-2"]
    assert result["numbers"]["weekly_limit_hours"] == 20
    assert result["numbers"]["violation_risk"] is False
    assert result["card"] is not None


def test_compliance_reason_default_check_type_works():
    # check_type 생략 시 기본값(jeonse_fraud)으로 동작해야 한다
    result = tools.compliance_reason(persona_id="minh")
    assert result["numbers"]["check_type"] == "jeonse_fraud"


# --- form_autofill ---

def test_form_autofill_minh_departure_insurance_claim():
    result = tools.form_autofill(persona_id="minh", form_id="departure_insurance_claim")
    form = data.GOVERNMENT_FORMS["departure_insurance_claim"]
    assert result["numbers"]["autofill_fields"] == form["autofill_fields"]
    assert result["numbers"]["total_fields"] == form["total_fields"]
    assert result["numbers"]["manual_fields"] == form["total_fields"] - form["autofill_fields"]
    assert result["numbers"]["autofill_ratio"] == round(
        form["autofill_fields"] / form["total_fields"], 2
    )
    assert result["card"] is not None
    assert set(result["card"].keys()) == {"icon", "head", "body", "metric"}


def test_form_autofill_suman_alien_registration_renewal():
    result = tools.form_autofill(persona_id="suman", form_id="alien_registration_renewal")
    form = data.GOVERNMENT_FORMS["alien_registration_renewal"]
    assert result["numbers"]["autofill_fields"] == form["autofill_fields"]
    assert result["card"] is not None


def test_form_autofill_pension_return_claim_ratio():
    result = tools.form_autofill(persona_id="minh", form_id="pension_return_claim")
    # 14개 중 11개 자동 → 비율 0.79
    assert result["numbers"]["autofill_ratio"] == round(11 / 14, 2)
    assert result["numbers"]["manual_fields"] == 3


def test_form_autofill_invalid_form_returns_none_card():
    result = tools.form_autofill(persona_id="minh", form_id="nonexistent_form")
    assert result["numbers"]["total_fields"] == 0
    assert result["card"] is None


def test_form_autofill_default_form_id_works():
    # form_id 생략 시 기본값(alien_registration_renewal)으로 동작해야 한다
    result = tools.form_autofill(persona_id="minh")
    assert result["numbers"]["form_id"] == "alien_registration_renewal"
    assert result["card"] is not None


# --- 스키마 검증 ---

def test_every_tool_has_schema():
    from mcp_servers.docs import schemas
    from mcp_servers.docs.tools import TOOL_REGISTRY
    for name in TOOL_REGISTRY:
        assert name in schemas.TOOL_SCHEMAS, f"{name} 스키마 누락"
        s = schemas.TOOL_SCHEMAS[name]
        assert s["name"] == name
        assert "description" in s
        assert s["input_schema"]["type"] == "object"
