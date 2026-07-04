"""서류행정 부문 tool 3개. 순수 함수. MCP나 Claude를 모른다.
3엔진(Perception / Reasoning / Action) 기준.
입력은 키워드 인자, 출력은 {summary, detail, numbers, card} dict."""

from shared.personas import get_persona
from mcp_servers.docs import data


def perception_parse(persona_id: str, doc_type: str = "alien_registration") -> dict:
    """OCR로 서류를 파싱하고 실명 불일치를 검출한다. (Perception 엔진)"""
    p = get_persona(persona_id)
    doc = data.DOC_TYPES.get(doc_type)

    if doc is None:
        return {
            "summary": f"지원하지 않는 서류 유형입니다: {doc_type}",
            "detail": f"지원 서류 유형: {list(data.DOC_TYPES.keys())}",
            "numbers": {
                "doc_type": doc_type,
                "field_count": 0,
                "name_matched": False,
                "confidence": 0.0,
                "needs_manual_review": True,
            },
            "card": None,
        }

    field_count = doc["field_count"]
    confidence = data.OCR_CONFIDENCE_BASE
    name_matched = True  # mock: 기본 일치 (불일치율 data.OCR_MISMATCH_RATE = 6%)
    needs_review = confidence < data.OCR_CONFIDENCE_THRESHOLD

    numbers = {
        "doc_type": doc_type,
        "doc_name_ko": doc["name_ko"],
        "field_count": field_count,
        "name_matched": name_matched,
        "confidence": confidence,
        "needs_manual_review": needs_review,
    }

    if not name_matched:
        return {
            "summary": f"{doc['name_ko']} 파싱 완료 — 실명 불일치 감지됨.",
            "detail": (
                f"{p['name']}님의 {doc['name_ko']}를 파싱했습니다. "
                f"서류상 이름이 등록 정보와 불일치합니다. 담당자 확인이 필요합니다. "
                f"OCR 신뢰도: {confidence:.0%}."
            ),
            "numbers": numbers,
            "card": {
                "icon": "",
                "head": f"{doc['name_ko']} 실명 불일치 감지",
                "body": "서류 이름이 등록 정보와 다릅니다. 담당자 확인 후 진행하세요.",
                "metric": f"신뢰도 {confidence:.0%}",
            },
        }

    return {
        "summary": f"{doc['name_ko']} 파싱 완료 — 실명 일치. {field_count}개 항목 추출.",
        "detail": (
            f"{p['name']}님의 {doc['name_ko']}를 OCR로 파싱했습니다. "
            f"{field_count}개 필드 추출 완료, 실명 일치 확인. "
            f"OCR 신뢰도 {confidence:.0%}. 서류 자동작성에 바로 활용 가능합니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"{doc['name_ko']} 파싱 완료",
            "body": f"{field_count}개 항목 추출. 실명 일치. 자동작성에 바로 활용 가능합니다.",
            "metric": f"신뢰도 {confidence:.0%}",
        },
    }


def compliance_reason(persona_id: str, check_type: str = "jeonse_fraud") -> dict:
    """준법 추론과 전세사기와 비자 가드레일 심사를 한다. (Reasoning 엔진)"""
    p = get_persona(persona_id)

    if check_type == "jeonse_fraud":
        risk_count = len(data.JEONSE_FRAUD_INDICATORS)
        # D-2(유학) 비자만 통상 기숙사/고시원 거주로 전세계약 해당 없음.
        # E-9(근로자), F-2(거주) 등 임대차 계약 주체가 될 수 있는 비자는 위험 점검 대상.
        _DORM_VISA = {"D-2"}
        has_lease_risk = p["visa"] not in _DORM_VISA

        if not has_lease_risk:
            return {
                "summary": (
                    f"{p['name']}님({p['visa']})은 전세계약 해당 없음. "
                    f"전세사기 위험 가드레일 불필요."
                ),
                "detail": (
                    f"{p['visa']} 유학비자는 통상 기숙사 또는 고시원 거주라 전세계약 해당 없습니다. "
                    f"향후 독립 거주 시 {risk_count}개 위험 지표를 반드시 점검하세요. "
                    f"외국인 전세사기 피해자 비율은 전체의 "
                    f"{data.JEONSE_FRAUD_FOREIGN_VICTIM_RATE * 100:.0f}%입니다."
                ),
                "numbers": {
                    "check_type": check_type,
                    "has_lease_risk": has_lease_risk,
                    "risk_indicator_count": risk_count,
                    "foreign_victim_rate": data.JEONSE_FRAUD_FOREIGN_VICTIM_RATE,
                    "jeonse_ratio_danger": data.JEONSE_RATIO_DANGER,
                    "risk_level": "해당없음",
                },
                "card": None,
            }

        return {
            "summary": (
                f"{p['name']}님의 전세계약 위험 지표 {risk_count}개를 점검합니다. "
                f"전세가율 {data.JEONSE_RATIO_DANGER * 100:.0f}% 초과 시 고위험."
            ),
            "detail": (
                f"외국인 전세사기 피해자 비율은 전체의 "
                f"{data.JEONSE_FRAUD_FOREIGN_VICTIM_RATE * 100:.0f}%입니다. "
                f"주요 위험 지표 {risk_count}개: "
                + " / ".join(data.JEONSE_FRAUD_INDICATORS)
                + f". 전세가율 {data.JEONSE_RATIO_DANGER * 100:.0f}% 초과 시 계약 중단, "
                f"{data.JEONSE_RATIO_CAUTION * 100:.0f}~{data.JEONSE_RATIO_DANGER * 100:.0f}% 구간은 주의."
            ),
            "numbers": {
                "check_type": check_type,
                "has_lease_risk": has_lease_risk,
                "risk_indicator_count": risk_count,
                "foreign_victim_rate": data.JEONSE_FRAUD_FOREIGN_VICTIM_RATE,
                "jeonse_ratio_danger": data.JEONSE_RATIO_DANGER,
                "jeonse_ratio_caution": data.JEONSE_RATIO_CAUTION,
                "risk_level": "점검필요",
            },
            "card": {
                "icon": "",
                "head": f"전세사기 위험 지표 {risk_count}개 점검",
                "body": (
                    f"전세가율 {data.JEONSE_RATIO_DANGER * 100:.0f}% 초과 시 계약 전 필수 확인. "
                    f"외국인 피해 비율 {data.JEONSE_FRAUD_FOREIGN_VICTIM_RATE * 100:.0f}%."
                ),
                "metric": f"위험 지표 {risk_count}개",
            },
        }

    elif check_type == "visa_work_eligibility":
        visa = p["visa"]
        weekly_limit = data.VISA_WORK_LIMITS.get(visa)

        if visa == "E-9":
            return {
                "summary": f"{p['name']}님(E-9)은 지정 사업장 외 취업 불가. 무단 이탈 시 비자 취소.",
                "detail": (
                    "E-9 비자는 고용허가서에 기재된 사업장에서만 근무 가능합니다. "
                    "허가 없이 다른 사업장에서 근무하면 불법 취업으로 비자 취소 및 강제출국 대상입니다. "
                    "사업장 변경이 필요하면 고용노동부 허가를 먼저 받아야 합니다."
                ),
                "numbers": {
                    "check_type": check_type,
                    "visa": visa,
                    "weekly_limit_hours": weekly_limit,
                    "work_restriction": "지정_사업장_한정",
                    "violation_risk": True,
                },
                "card": {
                    "icon": "",
                    "head": "E-9: 지정 사업장만 취업 가능",
                    "body": "허가 없이 다른 사업장 근무 시 비자 취소. 사업장 변경 시 고용노동부 허가 필수.",
                    "metric": "무단 사업장 변경 = 비자 취소",
                },
            }
        elif visa == "D-2":
            return {
                "summary": f"{p['name']}님(D-2)은 주 {weekly_limit}시간 이내 아르바이트 가능.",
                "detail": (
                    f"D-2 유학비자는 시간제 취업 허가(교내외 아르바이트) 주 {weekly_limit}시간 이내입니다. "
                    f"방학 기간에는 시간 제한 없이 취업 가능합니다. "
                    f"주 {weekly_limit}시간 초과 근무는 불법 취업으로 비자 취소 위험입니다."
                ),
                "numbers": {
                    "check_type": check_type,
                    "visa": visa,
                    "weekly_limit_hours": weekly_limit,
                    "work_restriction": "주_20시간_이내",
                    "violation_risk": False,
                },
                "card": {
                    "icon": "",
                    "head": f"D-2: 주 {weekly_limit}시간 이내 근무 가능",
                    "body": f"주 {weekly_limit}시간 초과 시 불법. 방학 기간은 제한 없음.",
                    "metric": f"주 {weekly_limit}시간 제한",
                },
            }
        elif visa == "F-2":
            return {
                "summary": f"{p['name']}님(F-2 거주비자)은 별도 허가 없이 자유롭게 취업 가능합니다.",
                "detail": (
                    "F-2 거주비자는 취업 활동에 별도 제한이 없습니다. "
                    "업종과 사업장에 관계없이 자유로운 취업이 가능합니다. "
                    "다만 비자 체류 기간 내에서만 취업 자격이 유효합니다."
                ),
                "numbers": {
                    "check_type": check_type,
                    "visa": visa,
                    "weekly_limit_hours": weekly_limit,
                    "work_restriction": "제한없음",
                    "violation_risk": False,
                },
                "card": {
                    "icon": "",
                    "head": "F-2: 취업 제한 없음",
                    "body": "업종과 사업장에 관계없이 자유로운 취업 가능. 체류 기간 내 자격 유효.",
                    "metric": "취업 자유",
                },
            }
        elif visa == "D-10":
            return {
                "summary": f"{p['name']}님(D-10 구직비자)은 구직 활동 중 제한적 취업 가능합니다.",
                "detail": (
                    "D-10 구직비자는 취업 활동이 원칙적으로 허용되지 않습니다. "
                    "출입국 당국으로부터 시간제 취업 허가를 받은 경우에 한해 제한적으로 취업 가능합니다. "
                    "허가 없이 취업하면 불법 취업으로 비자 취소 및 출국 조치 대상이 됩니다."
                ),
                "numbers": {
                    "check_type": check_type,
                    "visa": visa,
                    "weekly_limit_hours": weekly_limit,
                    "work_restriction": "허가_조건부",
                    "violation_risk": True,
                },
                "card": {
                    "icon": "",
                    "head": "D-10: 허가 없는 취업 불가",
                    "body": "출입국 당국 허가를 받은 경우에만 제한적 취업 가능. 무허가 취업 시 비자 취소.",
                    "metric": "취업 허가 조건부",
                },
            }
        else:
            # 위에 명시되지 않은 비자 유형
            return {
                "summary": (
                    f"{p['name']}님({visa})은 별도의 취업 가능 조건 확인이 필요합니다. "
                    "출입국 당국 기준을 따릅니다."
                ),
                "detail": (
                    f"해당 비자({visa})는 취업 조건이 비자 유형별로 다르게 적용됩니다. "
                    "출입국관리법 및 출입국 당국의 최신 고시를 확인하거나 "
                    "가까운 출입국 외국인청에 문의하시기 바랍니다."
                ),
                "numbers": {
                    "check_type": check_type,
                    "visa": visa,
                    "weekly_limit_hours": weekly_limit,
                    "work_restriction": "확인필요",
                    "violation_risk": None,
                },
                "card": {
                    "icon": "",
                    "head": f"{visa}: 취업 조건 확인 필요",
                    "body": "출입국 당국 기준에 따라 취업 가능 여부가 결정됩니다. 직접 문의 권장.",
                    "metric": "개별 확인 필요",
                },
            }

    # 알 수 없는 check_type
    return {
        "summary": f"지원하지 않는 심사 유형입니다: {check_type}",
        "detail": "지원 심사 유형: jeonse_fraud, visa_work_eligibility",
        "numbers": {
            "check_type": check_type,
            "risk_indicator_count": 0,
            "foreign_victim_rate": 0.0,
            "risk_level": "알수없음",
        },
        "card": None,
    }


def form_autofill(persona_id: str, form_id: str = "alien_registration_renewal") -> dict:
    """정부 PDF 신청서를 원클릭 자동작성한다. (Action 엔진)"""
    p = get_persona(persona_id)
    form = data.GOVERNMENT_FORMS.get(form_id)

    if form is None:
        return {
            "summary": f"지원하지 않는 신청서 양식입니다: {form_id}",
            "detail": f"지원 양식: {list(data.GOVERNMENT_FORMS.keys())}",
            "numbers": {
                "form_id": form_id,
                "total_fields": 0,
                "autofill_fields": 0,
                "manual_fields": 0,
                "autofill_ratio": 0.0,
            },
            "card": None,
        }

    total = form["total_fields"]
    auto = form["autofill_fields"]
    manual = total - auto
    ratio = auto / total

    numbers = {
        "form_id": form_id,
        "form_name_ko": form["name_ko"],
        "total_fields": total,
        "autofill_fields": auto,
        "manual_fields": manual,
        "autofill_ratio": round(ratio, 2),
    }

    return {
        "summary": (
            f"{p['name']}님의 {form['name_ko']}를 {auto}/{total}개 항목 자동작성 완료. "
            f"{manual}개 항목만 직접 입력하면 됩니다."
        ),
        "detail": (
            f"{form['name_ko']} 총 {total}개 항목 중 {auto}개({ratio * 100:.0f}%)를 "
            f"페르소나 데이터로 자동 완성했습니다. "
            f"나머지 {manual}개 항목(서명, 날짜 등)은 {p['name']}님이 직접 입력합니다. "
            f"작성된 서류는 PDF로 저장하거나 담당 창구에 제출할 수 있습니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"{form['name_ko']} {auto}/{total}개 자동완성",
            "body": (
                f"나머지 {manual}개 항목만 직접 입력하면 제출 준비 완료. "
                f"서명과 날짜 등 본인 확인 항목입니다."
            ),
            "metric": f"자동완성 {ratio * 100:.0f}%",
        },
    }


TOOL_REGISTRY = {
    "perception_parse": perception_parse,
    "compliance_reason": compliance_reason,
    "form_autofill": form_autofill,
}

ACTIVE_TOOLS = ["perception_parse", "form_autofill"]
