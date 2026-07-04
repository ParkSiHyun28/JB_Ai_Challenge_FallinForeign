"""서류행정 부문 상수. 정부 신청서 자동작성(form_autofill) 전용.
출처: 관계 법령, 출입국관리법, JB금융 외국인 서비스 사례.

회원 신원/프로필 정본은 shared/personas.py다. FORM_FIELD_MAPPING의 람다가
get_profile(p)로 정본을 소비한다. 자체 사본을 두지 않는다.
스캔/OCR과 준법심사는 제거됐다(페르소나 정보로 채우는 방식으로 통일).
"""

from shared.personas import get_profile

# --- 정부 신청서 메타 (총 필드 수, 자동기재 필드 수) ---
GOVERNMENT_FORMS = {
    "pension_return_claim": {
        "name_ko": "국민연금 반환일시금 신청서",
        "total_fields": 14,
        "autofill_fields": 13,   # 국내계좌(금융기관과 계좌번호) 2페이지 자동기재 포함
    },
    "departure_insurance_claim": {
        "name_ko": "출국만기보험 청구서",
        "total_fields": 10,
        "autofill_fields": 8,
    },
    "alien_registration_renewal": {
        "name_ko": "외국인등록증 갱신 신청서",
        "total_fields": 12,
        "autofill_fields": 9,
    },
    "foreign_worker_tax": {
        "name_ko": "외국인 근로자 세금 정산 신청서",
        "total_fields": 16,
        "autofill_fields": 12,
    },
    "departure_postpone": {
        "name_ko": "출국기한유예신청서",
        "total_fields": 12,
        "autofill_fields": 7,
    },
    "residence_confirmation": {
        "name_ko": "거주 및 숙소제공 확인서",
        "total_fields": 15,
        "autofill_fields": 5,   # 외국인(tenant) 란만 자동. 제공자 란은 직접입력.
    },
    "parttime_work_confirmation": {
        "name_ko": "외국인 유학생 시간제취업 확인서",
        "total_fields": 15,
        "autofill_fields": 3,   # 대상자(학생) 란만 자동. 근무처와 학교 란은 직접입력.
    },
}

# 신청서별 회원 프로필 매핑.
# callable이면 persona dict를 받아 값을 반환, 문자열이면 고정값.
# 상대방(고용주와 학교와 숙소제공자) 정보는 회원 프로필에 없으므로 manual(직접입력)로 둔다.
FORM_FIELD_MAPPING = {
    "pension_return_claim": {
        "autofill": {
            "성명":        lambda p: p["name"],
            "영문성명":    lambda p: p["name_en"],
            "국적":        lambda p: p["country"],
            "체류자격":    lambda p: p["visa"],
            "입국일":      lambda p: p["entry_date"],
            "출국예정일":  lambda p: p["exit_plan"],
            "납부월수":    lambda p: str(p["pension_months"]),
            "월평균소득":  lambda p: f"{p['monthly_wage_krw']:,}원",
            "신청유형":    "반환일시금",
            "제출처":      "국민연금공단",
            "수령방법":    "계좌이체",
            "금융기관":    lambda p: get_profile(p).get("bank_name", ""),
            "계좌번호":    lambda p: get_profile(p).get("bank_account", ""),
        },
        "manual": ["서명", "신청일자"],
    },
    "departure_insurance_claim": {
        "autofill": {
            "성명":        lambda p: p["name"],
            "영문성명":    lambda p: p["name_en"],
            "국적":        lambda p: p["country"],
            "체류자격":    lambda p: p["visa"],
            "입국일":      lambda p: p["entry_date"],
            "출국예정일":  lambda p: p["exit_plan"],
            "월통상임금":  lambda p: f"{p['monthly_wage_krw']:,}원",
            "청구사유":    "출국",
        },
        "manual": ["서명", "출국일자"],
    },
    "alien_registration_renewal": {
        "autofill": {
            "성명":        lambda p: p["name"],
            "영문성명":    lambda p: p["name_en"],
            "국적":        lambda p: p["country"],
            "현재체류자격": lambda p: p["visa"],
            "입국일":      lambda p: p["entry_date"],
            "신청유형":    "갱신",
            "제출처":      "출입국외국인사무소",
            "수수료":      "30,000원",
            "구비서류":    "여권, 외국인등록증, 사진 1매",
        },
        "manual": ["서명", "신청일자", "연락처"],
    },
    "foreign_worker_tax": {
        "autofill": {
            "성명":        lambda p: p["name"],
            "영문성명":    lambda p: p["name_en"],
            "국적":        lambda p: p["country"],
            "체류자격":    lambda p: p["visa"],
            "입국일":      lambda p: p["entry_date"],
            "월소득":      lambda p: f"{p['monthly_wage_krw']:,}원",
            "과세유형":    "단일세율 19%",
            "신청유형":    "연말정산",
            "제출처":      "관할 세무서",
            "납세구분":    "거주자",
            "소득구분":    "근로소득",
            "공제항목":    "기본공제",
        },
        "manual": ["서명", "신청일자", "계좌번호", "사업자등록번호"],
    },
    "departure_postpone": {
        "autofill": {
            "성명":       lambda p: p["name"],
            "생년월일":   lambda p: get_profile(p).get("reg_no", ""),
            "성별":       lambda p: get_profile(p).get("gender", ""),
            "국적":       lambda p: get_profile(p).get("nationality", p["country"]),
            "국내체류지": lambda p: get_profile(p).get("address_kr", ""),
            "출국예정일": lambda p: p["exit_plan"],
            "신청일":     "자동",
        },
        "manual": ["한자성명", "본국주소", "출국예정항", "신청사유", "서명"],
    },
    "residence_confirmation": {
        "autofill": {
            "국적":         lambda p: get_profile(p).get("nationality", p["country"]),
            "외국인등록번호": lambda p: get_profile(p).get("reg_no", ""),
            "성명":         lambda p: p["name"],
            "연락처":       lambda p: get_profile(p).get("phone", ""),
            "주소":         lambda p: get_profile(p).get("address_kr", ""),
        },
        # 숙소 제공자(고용주) 란은 회원 정보에 없으므로 직접입력
        "manual": ["제공자_국적", "제공자_성명", "제공자_등록번호", "제공자_연락처",
                   "외국인과의관계", "소유형태", "주거형태", "제공일", "확인일자", "업체명"],
    },
    "parttime_work_confirmation": {
        "autofill": {
            "성명":         lambda p: p["name"],
            "외국인등록번호": lambda p: get_profile(p).get("reg_no", ""),
            "전화번호":     lambda p: get_profile(p).get("phone", ""),
        },
        # 근무처와 학교 란은 회원 정보에 없으므로 직접입력
        "manual": ["학과전공", "이수학기", "이메일", "업체명", "사업자등록번호", "업종",
                   "근무처주소", "고용주", "취업기간", "급여시급", "근무시간", "유학생담당자"],
    },
}
