"""자산 부문 mock 상수. 모든 수치는 검증된 출처가 있다.
출처: 03_작업기록/출처_검증_목록.md"""

# 송금 수수료율 (한도제한계좌 기본 경로 대 대안 경로)
REMIT_FEE_DEFAULT = 0.0515   # 5.15% 한도제한계좌 평균
REMIT_FEE_ALT = 0.016        # 1.6% WireBarley 등 대안 경로
REMIT_ROUTES = [
    {"name": "은행 한도제한계좌", "fee_rate": 0.0515},
    {"name": "하나은행 GLN", "fee_rate": 0.025},
    {"name": "WireBarley", "fee_rate": 0.016},
]

# 출국만기보험 적립률 (월 통상임금 기준)
SEVERANCE_INSURANCE_RATE = 0.083  # 8.3%

# 예금담보대출 한도 (예금액 기준)
COLLATERAL_LOAN_RATIO = 0.95  # 95%

# 국민연금 반환일시금 (외국인 평균 기준 산출 보조)
# 2023년 외국인 반환일시금 총 지급액 3,294억 원
PENSION_TOTAL_PAYOUT_2023_KRW = 329_400_000_000
# 미청구 휴면보험금 규모와 반환율
UNCLAIMED_INSURANCE_KRW = 30_760_000_000
UNCLAIMED_RETURN_RATE = 0.30
# 출국만기보험/반환일시금 청구 소멸시효, 근로자퇴직급여보장법/국민연금법 기준
CLAIM_DEADLINE_YEARS = 3
# 반환일시금 월 환산 추정 보조 (납부월수 * 월 적립 추정)
# mod_asset.js 근거: 58개월 기준 약 496만 원 → 월 약 85,517원
PENSION_MONTHLY_REFUND_KRW = 85_517

# 대안신용 (Thin Filer 축적)
CREDIT_PROFILE_MIN_MONTHS = 6   # 프로필 형성 최소 개월
CREDIT_PROFILE_FULL_MONTHS = 18  # 완성 개월

# 유학생 취업전환 통계
STUDENT_JOB_HOPE_RATE = 0.865   # 86.5% 한국취업 희망
STUDENT_VISA_CONVERT_RATE = 0.224  # 22.4% 실제 비자전환
