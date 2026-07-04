"""서류행정 부문 mock 상수. 3엔진(Perception / Reasoning / Action) 기준.
출처: 관계 법령, 출입국관리법, JB금융 외국인 서비스 사례."""

# --- Perception 엔진: OCR 서류 파싱 ---
DOC_TYPES = {
    "alien_registration": {
        "name_ko": "외국인등록증",
        "field_count": 5,
    },
    "lease_contract": {
        "name_ko": "임대차계약서",
        "field_count": 6,
    },
    "passport": {
        "name_ko": "여권",
        "field_count": 5,
    },
    "bank_statement": {
        "name_ko": "통장사본",
        "field_count": 4,
    },
}
OCR_CONFIDENCE_BASE = 0.95        # mock 기본 신뢰도
OCR_CONFIDENCE_THRESHOLD = 0.85   # 이하면 수동 검토 요청
OCR_MISMATCH_RATE = 0.06          # 명의 불일치 발생률 6% (통계)

# --- Reasoning 엔진: 준법 추론 ---
JEONSE_FRAUD_INDICATORS = [
    "시세 대비 전세가율 80% 초과",
    "임대인 선순위 채권 과다",
    "전입신고 후 확정일자 미취득",
    "중개사 등록 여부 미확인",
]
JEONSE_RATIO_DANGER = 0.80         # 80% 초과 시 고위험
JEONSE_RATIO_CAUTION = 0.70        # 70~80% 주의
JEONSE_FRAUD_FOREIGN_VICTIM_RATE = 0.18  # 전세사기 피해자 중 외국인 비율 18%

# 비자별 주당 취업 허용 시간 (None = 시간 아닌 장소/조건 제한)
VISA_WORK_LIMITS = {
    "E-9": None,   # 지정 사업장 외 취업 불가
    "D-2": 20,     # 교내외 아르바이트 주 20시간 이내
    "D-10": None,  # 구직활동 비자. 제한적 취업 허용(출입국당국 허가 조건)
    "F-2": None,   # 거주 비자. 취업 제한 없이 자유로운 취업 가능
}

# --- Action 엔진: 정부 신청서 자동작성 ---
GOVERNMENT_FORMS = {
    "pension_return_claim": {
        "name_ko": "국민연금 반환일시금 신청서",
        "total_fields": 14,
        "autofill_fields": 11,
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
}
