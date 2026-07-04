"""자산 부문 mock 상수. 모든 수치는 검증된 출처가 있다.
출처: 03_작업기록/출처_검증_목록.md 와 2026-07-04 자산부문 고도화 조사(1차 출처 명기).

원칙:
- 모든 계산은 이 파일 상수 × 페르소나 값으로만 한다. LLM이 수치를 만들지 않는다.
- 미확인이거나 준용한 값은 반드시 '가정' 주석을 붙인다.
"""

# ===========================================================================
# 연금 (국민연금 반환일시금)
# 공식: 반환일시금 = 납부한 연금보험료(사업장가입자는 사용자 부담분 포함) + 이자
# 근거: 국민연금법 제77조 제2항. 공단 외국인 급여 안내
#       https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0084M0.do
# ===========================================================================

# 연금보험료율. 2025년까지 9%(근로자 4.5% + 사용자 4.5%).
# 2026년부터 매년 0.5%p 인상해 2033년 13% 도달.
# 출처: 공단 연금보험료 페이지 https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0038M0.do
NPS_RATE_BASE = 0.09          # ~2025년 납부분
NPS_RATE_STEP = 0.005         # 2026년부터 연간 인상폭
NPS_RATE_CAP = 0.13           # 2033년 도달 상한


def nps_rate_for_year(year: int) -> float:
    """해당 연도 납부분에 적용되는 연금보험료율."""
    if year <= 2025:
        return NPS_RATE_BASE
    return min(NPS_RATE_BASE + NPS_RATE_STEP * (year - 2025), NPS_RATE_CAP)


# 기준소득월액 상하한 (2026-07-01 ~ 2027-06-30 적용). 보험료 산정 시 월급을 이 범위로 자른다.
# 출처: 공단 연금보험료 페이지 (위와 동일)
NPS_INCOME_MIN_KRW = 410_000
NPS_INCOME_MAX_KRW = 6_590_000

# 반환일시금 이자: 3년 만기 정기예금 이자율. 납부월 다음 달부터 지급사유 발생월까지 월할 단리.
# 2025년 적용치 2.6%. 2026년 적용치는 공단 미공시라 2025년 값을 준용한다(가정).
# 출처: 공단 반환일시금 페이지 https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0079M0.do
NPS_INTEREST_RATE = 0.026

# 반환일시금 청구 소멸시효(년). 사유별로 다르다.
# - 출국(국외이주, 국적상실) 사유: 5년  ← 우리 서비스 대상(E-9 귀국자)에 적용되는 값
# - 60세 도달 사유: 10년 (2018-01-25 개정)
# 출처: 국민연금법 제115조. 공단 외국인 급여 페이지 원문(2026-06-15 기준) 확인
PENSION_REFUND_DEADLINE_YEARS = 5          # 출국 사유 (서비스 기본값)
PENSION_REFUND_DEADLINE_YEARS_AGE60 = 10   # 60세 도달 사유 (참고용)

# 국가별 반환일시금 자격 테이블 (flag 코드 키). 백엔드 판정 엔진 전용. 화면 노출용 아님.
#  enrolled : 국민연금 가입 대상 여부 (상호주의. False면 보험료 공제 자체가 없음)
#  national : 국적 기준 반환일시금 수령 가능 여부 (상호주의 또는 협정)
#  e9_h2    : E-9, H-2 체류자격 특례 수령 가능 여부 (2007-05-11 이후 국적 무관)
#  min_months: 국적 기준 수령의 최소 납부월수 조건 (없으면 0)
# 출처: 공단 국가별 가입대상 PDF(2026-03) https://www.nps.or.kr/html/download/easy/national_join_202603.pdf
#       공단 반환일시금 지급 대상국(2026-06-15 기준) getOHAF0084M0 페이지 원문
NPS_ELIGIBILITY = {
    "VN": {"enrolled": True,  "national": False, "e9_h2": True,  "min_months": 0,
           "note": "합산협정 2024-01 발효. 베트남 국내법 마련 전까지 국적 기준 지급 보류"},
    "NP": {"enrolled": False, "national": False, "e9_h2": False, "min_months": 0,
           "note": "사업장/지역 모두 가입 제외국. 보험료 공제 자체가 없음"},
    "TH": {"enrolled": True,  "national": True,  "e9_h2": True,  "min_months": 12,
           "note": "상호주의. 가입 1년 이상 조건"},
    "ID": {"enrolled": True,  "national": True,  "e9_h2": True,  "min_months": 0,
           "note": "상호주의. 기간 무관"},
    "KH": {"enrolled": True,  "national": True,  "e9_h2": True,  "min_months": 0,
           "note": "상호주의. 사업장 가입은 2023-03-29부터"},
    "MM": {"enrolled": False, "national": False, "e9_h2": False, "min_months": 0,
           "note": "가입 제외국"},
    "PH": {"enrolled": True,  "national": True,  "e9_h2": True,  "min_months": 0,
           "note": "합산협정 2024-04-01 발효"},
    "BD": {"enrolled": False, "national": False, "e9_h2": False, "min_months": 0,
           "note": "가입 제외국"},
    "IN": {"enrolled": True,  "national": True,  "e9_h2": True,  "min_months": 0,
           "note": "합산협정 2011-11-01 발효"},
    "UZ": {"enrolled": True,  "national": False, "e9_h2": True,  "min_months": 0,
           "note": "보험료 면제협정만 체결. 국적 기준 지급 대상국 아님"},
    "CN": {"enrolled": True,  "national": False, "e9_h2": True,  "min_months": 0,
           "note": "면제협정 2013-01-16 발효. 국적 기준 지급 대상국 아님"},
    "MN": {"enrolled": True,  "national": False, "e9_h2": True,  "min_months": 0,
           "note": "면제협정만 체결. 국적 기준 지급 대상국 아님"},
}

# 특례 수령이 인정되는 체류자격. 국적 무관 (2007-05-11 이후).
# 주의: 현행 E-8(계절근로. 2019-12 신설)은 특례 대상이 아니다. 과거 연수취업 E-8만 해당.
# 출처: 공단 FAQ https://www.nps.or.kr/pnsinfo/ntpsklg/getOHAF0100M0.do
NPS_SPECIAL_VISAS = ("E-9", "H-2")

# 2023년 외국인 반환일시금 총 지급액 3,294억 원 (발표 근거용 통계)
PENSION_TOTAL_PAYOUT_2023_KRW = 329_400_000_000

# ===========================================================================
# 보험 (출국만기보험)
# ===========================================================================

# 출국만기보험 적립률 (월 통상임금 기준). E-9 사업장 의무 가입.
SEVERANCE_INSURANCE_RATE = 0.083  # 8.3%

# 출국만기보험 청구 소멸시효 3년. 지급사유(출국) 발생일부터. 시효 완성 시 보험금은
# 한국산업인력공단으로 이관된다. 출처: 외국인고용법 전용보험 규정(찾기쉬운 생활법령정보).
CLAIM_DEADLINE_YEARS = 3

# 미청구 휴면보험금 규모와 반환율
UNCLAIMED_INSURANCE_KRW = 30_760_000_000
UNCLAIMED_RETURN_RATE = 0.30

# ===========================================================================
# 예금 (예금담보대출)
# ===========================================================================

# 예금담보대출 한도 (예금액 기준)
COLLATERAL_LOAN_RATIO = 0.95  # 95%

# ===========================================================================
# 송금 (총비용 = 고정수수료 + 부가비용 + 환율마진 × 금액)
# 근거: 각 사 공식 수수료표 + World Bank Remittance Prices Worldwide 원데이터(2025 3Q)
#       https://datacatalogfiles.worldbank.org/ddh-published/0037898/DR0095523/rpw_dataset_2011_2025_q3.xlsx
# ===========================================================================

REMIT_ROUTES_TC = [
    {
        "id": "bank_counter", "name": "은행 창구 송금",
        "fixed_fee_krw": 18_000,   # 송금수수료 10,000(USD 2,000 이하) + 전신료 8,000. KB/하나 공식 수수료표
        "spread_rate": 0.010,      # RPW 2025 3Q 은행 환율마진 평균 약 1.0%
        "extra_fee_krw": 27_000,   # OUR(송금인 부담) 중계은행 수수료 약 USD 18 상당
    },
    {
        "id": "bank_internet", "name": "은행 인터넷 송금",
        "fixed_fee_krw": 8_000,    # 수수료 3,000 + 전신료 5,000
        "spread_rate": 0.010,
        "extra_fee_krw": 0,
    },
    {
        "id": "hana_ez", "name": "하나 EZ 간편송금",
        "fixed_fee_krw": 5_000,    # 하나은행 공식: 제휴처송금 미화 1만불 이하 건당 5,000원
        "spread_rate": 0.010,      # 공시 없음. 은행 환율마진 준용(가정)
        "extra_fee_krw": 0,
    },
    {
        "id": "fintech", "name": "소액해외송금업체",
        "fixed_fee_krw": 4_000,    # 실측 2,000~5,000원 범위 중간값 (RPW Moin, 한패스 공식)
        "spread_rate": 0.006,      # RPW 실측 핀테크 환율마진 0.48~0.63%
        "extra_fee_krw": 0,
    },
]

# 수취 통화 표기용 환산 (2026-07 초 시장환율 근사. 표기 전용. 계산에는 쓰지 않는다)
FX_DISPLAY = {"VN": ("VND", 17.0), "NP": ("NPR", 0.099)}

# 검증 기준점: 한국→베트남 200USD 평균 총비용률 5.15% (World Bank RPW 2025 3Q 실측)
# 주의: 이 수치는 송금 평균 총비용률이다. 한도제한계좌 수수료가 아니다(과거 주석 오류 정정).
# 한국→네팔 통로는 RPW 미조사. 네팔 안내 시 베트남 통로 준용을 명시한다.
RPW_KR_VN_200USD_TOTAL_COST = 0.0515

# ===========================================================================
# 신용 (대안신용 축적. Thin Filer)
# 근거: KCB 평가기준 공시 https://www.allcredit.co.kr/screen/sc0682112929
#       KCB 제휴 신용점수올리기 안내(12/36개월) https://www.shinhansec.com/siw/html/etc/credit_score_landing.html
# ===========================================================================

# 신용 사다리: 연체 없는 연속 납부 개월수 기준 단계 (KCB 확인치)
CREDIT_LADDER = [
    {"months": 12, "label": "KCB 가점 반영 최소선", "desc": "연체 없는 연속 12개월 납부 이력부터 가점 반영"},
    {"months": 36, "label": "KCB 최대 가점 조건", "desc": "36개월 충족 시 최대 가점"},
]

# KCB 평가에서 비금융/마이데이터 비중 11% (공시 확인치)
CREDIT_KCB_NONFIN_WEIGHT = 0.11

# 납부 이력 항목 구분.
# - OFFICIAL: 현행 CB사(KCB/NICE) 등록 반영 항목 (확인됨)
# - PROPOSED: 현행 CB 미반영. JB 제안 모델로 정직 표기 (월세는 반영 항목이 아님이 확인됨)
CREDIT_ITEMS_OFFICIAL = ("통신요금", "공과금", "국민연금", "건강보험")
CREDIT_ITEMS_PROPOSED = ("월세",)

# 통신 3사 합작 대안신용평가사 EQUAL: 외국인 전용 평가모형 출시(2025. 케이뱅크 도입).
# detail 근거 인용용. 출처: https://www.equal.co.kr/news
CREDIT_EQUAL_NOTE = "통신 3사 합작 대안신용평가사(EQUAL)가 외국인 전용 모형을 운영 중"

# Thin Filer 통계 (발표 근거용. 2차 출처)
THIN_FILER_FOREIGNER_COUNT = 2_250_000  # 국내 거주 외국인 금융이력 부족 약 225만 명

# 유학생 취업전환 통계
STUDENT_JOB_HOPE_RATE = 0.865      # 86.5% 한국취업 희망
STUDENT_VISA_CONVERT_RATE = 0.224  # 22.4% 실제 비자전환

