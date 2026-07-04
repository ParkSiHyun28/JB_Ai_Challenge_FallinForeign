"""두 페르소나 공용 데이터. 모든 부문이 이 모듈을 import 한다."""

# 타입 힌트(tuple[int, int] 등)를 문자열로 지연 평가한다.
# 배포 환경의 파이썬 버전이 낮아도 어노테이션이 런타임에 안 깨지게 한다.
from __future__ import annotations

PERSONAS = {
    "minh": {
        "id": "minh",
        "name": "응웬 반 민",
        "name_en": "Nguyen Van Minh",
        "flag": "VN",
        "country": "베트남",
        "visa": "E-9",
        "role": "근로자",
        "entry_date": "2022-08",
        "exit_plan": "2027-01",
        "monthly_wage_krw": 2_700_000,
        "monthly_remit_krw": 1_000_000,
        "pension_months": 50,
        # 주의: 자산 tool은 이 bool을 더 이상 읽지 않는다(2026-07 고도화).
        # 판정은 mcp_servers/asset/data.py의 NPS_ELIGIBILITY 국가 테이블로 한다.
        # 필드 자체는 팀 규약(test_contract)과 타 부문 호환을 위해 유지한다.
        "social_security_treaty": False,
        "deposit_balance_krw": 0,
        "remit_route": "bank_counter",   # 현재 이용 송금 경로 (data.py REMIT_ROUTES_TC의 id)
        "credit_accrual_start": None,    # 대안신용 축적 시작월 "YYYY-MM". 출국 임박이라 미시작
        "summary": "베트남 E-9 근로자. 출국 임박. 반환일시금과 출국만기보험 수령 대상.",
        "reg_no": "920305-5680512",
        "gender": "M",
        "passport_no": "B1234567",
        "passport_issue": "2021.11.20",
        "passport_expiry": "2031.11.19",
        "address_kr": "전북특별자치도 전주시 덕진구 팔복로 123",
        "phone": "010-1234-5678",
        "email": "minh.nguyen@example.com",
        "address_home": "Hai Ba Trung, Ha Noi, Vietnam",
        "bank_name": "전북은행",
        "bank_account": "1013-45-678901",
        "occupation": "생산직",
        "workplace_name": "전주정밀공업(주)",
        "school_name": "",
        "school_type": "",
    },
    "suman": {
        "id": "suman",
        "name": "수만 라이",
        "name_en": "Suman Rai",
        "flag": "NP",
        "country": "네팔",
        "visa": "D-2",
        "role": "유학생",
        "entry_date": "2024-03",
        "exit_plan": "2027-02",
        "monthly_wage_krw": 0,
        "monthly_remit_krw": 0,
        "pension_months": 0,
        # 주의: 자산 tool은 이 bool을 더 이상 읽지 않는다. NPS_ELIGIBILITY 테이블 참조.
        # 네팔은 국민연금 가입 제외국(공단 국가별 PDF 2026-03)이라 반환일시금 자체가 해당 없음.
        "social_security_treaty": False,
        "deposit_balance_krw": 20_000_000,  # 잔고증명 요건
        "remit_route": None,               # 정기 송금 없음
        "credit_accrual_start": "2024-03",  # 입국월부터 통신비/공과금 납부 이력 축적 가정
        "summary": "네팔 D-2 유학생. Thin Filer. 잔고증명 예치금 보유. 대안신용 축적 대상.",
        "reg_no": "010218-7345678",
        "gender": "M",
        "passport_no": "PA0846213",
        "passport_issue": "2023.09.15",
        "passport_expiry": "2033.09.14",
        "address_kr": "전북특별자치도 전주시 완산구 천잠로 303 전주대학교 학생생활관",
        "phone": "010-9876-5432",
        "email": "suman.rai@example.com",
        "address_home": "Lalitpur, Kathmandu Valley, Nepal",
        "bank_name": "전북은행",
        "bank_account": "1013-98-765432",
        "occupation": "",
        "workplace_name": "",
        "school_name": "전주대학교",
        "school_type": "대학(학부)",
    },
}


def get_persona(persona_id: str) -> dict:
    """페르소나 식별자로 데이터를 반환한다. 고정 2명을 먼저 보고 없으면
    동적 페르소나 저장소를 본다. 둘 다 없으면 ValueError."""
    if persona_id in PERSONAS:
        return PERSONAS[persona_id]
    if persona_id in _DYNAMIC_PERSONAS:
        return _DYNAMIC_PERSONAS[persona_id]
    raise ValueError(f"unknown persona_id: {persona_id}")


# ---------------------------------------------------------------------------
# 동적 페르소나 생성기
# 전역 PERSONAS는 minh suman 2명으로 동결한다(test_contract가 강제).
# 50~100명 무작위 페르소나는 _DYNAMIC_PERSONAS에 따로 등록하고 get_persona가
# 폴백으로 읽는다. 모든 tool은 get_persona 한 곳만 보므로 이 폴백만으로 전 tool이
# 동적 페르소나에 자동 호환된다.
# ---------------------------------------------------------------------------
import random

# 데모 기준일. 생성기가 출국 예정일을 이 날짜 이후 미래로 보장하는 기준이다.
# 문자열 버전(DEMO_TODAY_STR)과 항상 같은 연월로 유지한다. backend/core.py가 import한다.
DEMO_TODAY = (2026, 10)
DEMO_TODAY_STR = "2026-10-03"  # 데모 기준일 전체 날짜. 민 출국 D-90 무렵.

# 비자에서 역할을 유도한다. visa와 role 불일치를 원천 차단한다.
VISA_ROLE = {"E-9": "근로자", "D-2": "유학생", "D-10": "구직자", "F-2": "거주자"}
# 비자별 법정 체류상한(개월). 입국일 역산에 쓴다.
VISA_MAX_STAY_MONTHS = {"E-9": 54, "D-2": 36, "D-10": 24, "F-2": 60}
# 비자별 가중 추첨용. 한국 체류 외국인 비율 근사.
_VISA_WEIGHTS = [("E-9", 0.55), ("D-2", 0.25), ("D-10", 0.12), ("F-2", 0.08)]
# 비자별 현실적 출신국 (country, flag) 풀.
_COUNTRY_POOL = {
    "E-9": [("베트남", "VN"), ("태국", "TH"), ("인도네시아", "ID"), ("캄보디아", "KH"), ("미얀마", "MM"), ("네팔", "NP"), ("필리핀", "PH")],
    "D-2": [("네팔", "NP"), ("베트남", "VN"), ("방글라데시", "BD"), ("인도", "IN"), ("우즈베키스탄", "UZ"), ("중국", "CN")],
    "D-10": [("베트남", "VN"), ("인도네시아", "ID"), ("네팔", "NP"), ("몽골", "MN")],
    "F-2": [("베트남", "VN"), ("중국", "CN"), ("필리핀", "PH"), ("태국", "TH")],
}
# 국가별 이름 풀. 없는 국가는 _NAME_FALLBACK로 폴백해 빈 이름이 안 나오게 한다.
# 각 항목은 (성 목록, 이름 목록, 영문성 후보, 영문이름 후보).
_NAME_POOL = {
    "VN": (["응웬", "쩐", "레", "팜"], ["반 민", "티 흐엉", "반 하이"], "Nguyen|Tran|Le|Pham", "Van Minh|Thi Huong|Van Hai"),
    "NP": (["라이", "샤르마", "타파"], ["수만", "비카스", "디팍"], "Rai|Sharma|Thapa", "Suman|Bikash|Dipak"),
}
_NAME_FALLBACK = (["카림", "아민", "라술"], ["하산", "오마르", "사이드"], "Karim|Amin|Rasul", "Hassan|Omar|Said")

# 국민연금 가입 제외국 flag. 원본은 mcp_servers/asset/data.py NPS_ELIGIBILITY(enrolled=False).
# shared가 mcp_servers를 import 하지 않도록(계층 역전 방지) 값만 복제하고 주석으로 동기를 강제한다.
_NPS_EXCLUDED_FLAGS = {"NP", "MM", "BD"}

# 동적 페르소나 저장소. 전역 PERSONAS는 동결 유지.
_DYNAMIC_PERSONAS: dict = {}


def _round_man(n: int) -> int:
    """만원 단위로 반올림한다."""
    return int(round(n / 10_000) * 10_000)


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """(연, 월)에 delta개월을 더해 (연, 월)을 돌려준다."""
    total = (year * 12 + (month - 1)) + delta
    ny, nm = divmod(total, 12)
    return ny, nm + 1


def _make_one(rng: random.Random, seq: int) -> dict:
    """무작위 페르소나 1명을 만든다. 출국 예정일을 데모 기준일 이후 미래로 먼저
    뽑고 입국일을 역산해 'D-day 음수' 페르소나가 생기지 않게 한다."""
    visa = rng.choices([v for v, _ in _VISA_WEIGHTS], weights=[w for _, w in _VISA_WEIGHTS])[0]
    role = VISA_ROLE[visa]
    country, flag = rng.choice(_COUNTRY_POOL[visa])
    last, first, last_en, first_en = _NAME_POOL.get(flag, _NAME_FALLBACK)
    last_en_list = last_en.split("|")
    first_en_list = first_en.split("|")
    # 한글 이름과 영문 이름은 같은 인덱스로 골라야 한 사람의 표기가 일치한다.
    # 따로 추첨하면 "아민 하산"인데 영문이 "Karim Said"처럼 엇갈린다.
    # 풀 길이가 다를 수 있으니 더 짧은 쪽 길이로 인덱스 범위를 맞춘다.
    li = rng.randrange(min(len(last), len(last_en_list)))
    fi = rng.randrange(min(len(first), len(first_en_list)))
    name = last[li] + " " + first[fi]
    name_en = last_en_list[li] + " " + first_en_list[fi]

    # 출국 예정일을 데모 기준일 + 3~36개월 미래에서 뽑는다. 그 뒤 비자 체류상한을
    # 빼서 입국일을 역산한다. 이러면 모든 페르소나가 출국 D-day 양수로 뜬다.
    # 역산한 입국일이 데모 기준일 이후(미래)가 될 수 있으므로 기준일 전월로 클램프한다.
    exit_offset = rng.randint(3, 36)
    ey, em = _add_months(DEMO_TODAY[0], DEMO_TODAY[1], exit_offset)
    entry_y, entry_m = _add_months(ey, em, -VISA_MAX_STAY_MONTHS[visa])
    # 클램프: 입국일이 기준일 이후이면 기준일 한 달 전으로 당긴다.
    clamp_y, clamp_m = _add_months(DEMO_TODAY[0], DEMO_TODAY[1], -1)
    if (entry_y, entry_m) >= (DEMO_TODAY[0], DEMO_TODAY[1]):
        entry_y, entry_m = clamp_y, clamp_m
    entry_date = f"{entry_y:04d}-{entry_m:02d}"
    exit_plan = f"{ey:04d}-{em:02d}"

    works = visa in ("E-9", "F-2")
    wage = _round_man(rng.randint(2_300_000, 3_600_000)) if works else 0
    remit = _round_man(int(wage * rng.uniform(0.3, 0.7))) if wage else 0
    pension = min(rng.randint(12, 60), 60) if visa == "E-9" else (rng.randint(0, 24) if visa == "F-2" else 0)
    # 국민연금 가입 제외국은 납부 이력 자체가 없다. 판정 원본은
    # mcp_servers/asset/data.py NPS_ELIGIBILITY(enrolled=False 국가)이며 여기와 동기 유지.
    if flag in _NPS_EXCLUDED_FLAGS:
        pension = 0
    deposit = _round_man(rng.randint(15_000_000, 40_000_000)) if visa in ("D-2", "D-10", "F-2") else 0
    # 송금자는 대부분 은행 경로를 쓴다고 가정(경로 개선 여지를 시연). 송금 없으면 None.
    remit_route = rng.choices(["bank_counter", "bank_internet"], weights=[0.7, 0.3])[0] if remit else None
    # 체류형(유학생/구직자/거주자)은 입국월부터 납부 이력 축적 가정. 출국 회수형(E-9)은 None.
    credit_start = entry_date if visa in ("D-2", "D-10", "F-2") else None
    pid = f"{visa.lower().replace('-', '')}_{flag.lower()}_{seq:03d}"
    summary = f"{country} {visa} {role}. 입국 {entry_date}. " + (
        "반환일시금과 출국만기보험 대상." if visa == "E-9" else
        "잔고증명 예치금 보유. 대안신용 축적 대상." if deposit else "체류 현황 점검 대상."
    )
    return {
        "id": pid, "name": name, "name_en": name_en, "flag": flag, "country": country,
        "visa": visa, "role": role, "entry_date": entry_date, "exit_plan": exit_plan,
        "monthly_wage_krw": wage, "monthly_remit_krw": remit, "pension_months": pension,
        "social_security_treaty": False, "deposit_balance_krw": deposit,
        "remit_route": remit_route, "credit_accrual_start": credit_start, "summary": summary,
    }


def make_random_personas(count: int = 60, seed: int = 42) -> dict:
    """무작위 페르소나 count명을 만든다. seed가 같으면 같은 결과(재현성).
    전역 random을 건드리지 않으려 자체 Random 인스턴스를 쓴다.
    id가 minh suman이나 서로 겹치지 않게 생성한다."""
    rng = random.Random(seed)
    out: dict = {}
    seq = 1
    while len(out) < count:
        p = _make_one(rng, seq)
        seq += 1
        if p["id"] in PERSONAS or p["id"] in out:
            continue
        out[p["id"]] = p
    return out


def register_personas(personas: dict) -> None:
    """동적 페르소나를 저장소에 등록한다. get_persona가 폴백으로 읽는다."""
    _DYNAMIC_PERSONAS.update(personas)


def all_personas() -> dict:
    """고정 2명과 동적 페르소나를 합친 전체를 반환한다. UI와 스키마가 쓴다.
    PERSONAS 자체는 동결이므로 합본은 매번 새 dict로 만든다."""
    merged = dict(PERSONAS)
    merged.update(_DYNAMIC_PERSONAS)
    return merged


def visa_expiry_info(
    persona_id_or_dict: str | dict,
    today: tuple[int, int] = DEMO_TODAY,
) -> dict:
    """비자 만료 관련 정보를 계산해 반환한다.

    반환 dict 키:
      expiry        : str  - 'YYYY-MM'. 비자 만료 연월.
      renewal_start : str  - 'YYYY-MM'. 갱신 신청 가능 시작 연월 (만료 4개월 전).
      months_left   : int  - 오늘(today) 기준 만료까지 남은 개월수.
                             양수=아직 남음. 0=이번 달 만료. 음수=이미 초과.
      renewal_needed: bool - True면 출국 전에 갱신이 필요함.
                             출국 예정일이 만료일보다 늦으면 True.
      status        : str  - 'ok' | 'renewal_window' | 'expired' | 'no_renewal'.
    """
    # 페르소나 dict 가져오기
    if isinstance(persona_id_or_dict, str):
        p = get_persona(persona_id_or_dict)
    else:
        p = persona_id_or_dict

    # 비자 코드 유효성 확인
    visa = p["visa"]
    if visa not in VISA_MAX_STAY_MONTHS:
        raise ValueError(f"unsupported visa: {visa}")

    # 입국일 파싱
    entry_y, entry_m = (int(v) for v in p["entry_date"].split("-"))

    # 비자 체류상한 읽기
    max_months = VISA_MAX_STAY_MONTHS[visa]

    # 만료일 계산
    exp_y, exp_m = _add_months(entry_y, entry_m, max_months)

    # 갱신 신청 가능 시작일 (만료 4개월 전)
    ren_y, ren_m = _add_months(exp_y, exp_m, -4)

    # 오늘 기준 만료까지 남은 개월수
    months_left = (exp_y * 12 + exp_m - 1) - (today[0] * 12 + today[1] - 1)

    # 출국 예정일 파싱
    xp_y, xp_m = (int(v) for v in p["exit_plan"].split("-"))

    # 갱신 필요 여부: 출국 예정일이 만료일보다 늦으면 갱신 필요
    renewal_needed = (xp_y, xp_m) > (exp_y, exp_m)

    # 상태 코드 결정
    # 우선순위: renewal_needed == False이면 months_left에 관계없이 'no_renewal'
    if not renewal_needed:
        status = "no_renewal"
    elif months_left < 0:
        status = "expired"
    elif months_left <= 4:
        status = "renewal_window"
    else:
        status = "ok"

    return {
        "expiry": f"{exp_y:04d}-{exp_m:02d}",
        "renewal_start": f"{ren_y:04d}-{ren_m:02d}",
        "months_left": months_left,
        "renewal_needed": renewal_needed,
        "status": status,
    }


# ---------------------------------------------------------------------------
# 회원 프로필 확장 필드 (PROFILE_CONTRACT.md 규약)
# 고정 2명(minh, suman)은 PERSONAS에 값을 직접 들고 있다. 동적 페르소나는 값이
# 없으므로 get_profile이 공란("")으로 채워 돌려준다. 서류행정 파트의
# _build_form_values()가 이 키를 그대로 받아 정부 신청서 PDF에 매핑한다.
#
# 중복 저장 금지: korean_name, nationality, visa_type은 기존 필드(name,
# country, visa)와 같은 정보라 dict에 저장하지 않는다. get_profile이 아래
# 대응표로 유도해 규약 키 그대로 출력한다.
# ---------------------------------------------------------------------------

# country(한글) → 국적 영문 표기. nationality를 저장하지 않고 유도한다.
COUNTRY_NAME_EN = {
    "베트남": "VIETNAM", "네팔": "NEPAL", "태국": "THAILAND",
    "인도네시아": "INDONESIA", "캄보디아": "CAMBODIA", "미얀마": "MYANMAR",
    "필리핀": "PHILIPPINES", "방글라데시": "BANGLADESH", "인도": "INDIA",
    "우즈베키스탄": "UZBEKISTAN", "중국": "CHINA", "몽골": "MONGOLIA",
}

# visa 코드 → 체류자격 표기. visa_type을 저장하지 않고 유도한다.
VISA_TYPE_LABEL = {
    "E-9": "비전문취업(E-9)", "D-2": "유학(D-2)",
    "D-10": "구직(D-10)", "F-2": "거주(F-2)",
}

# 프로필 규약 키와 한글 라벨. 응답 카드나 신청서 미리보기 UI가 라벨로 쓴다.
PROFILE_FIELD_LABELS = {
    "korean_name": "성명(국문)",
    "name_en": "성명(영문)",
    "nationality": "국적(영문)",
    "visa_type": "체류자격",
    "reg_no": "외국인등록번호",
    "gender": "성별",
    "passport_no": "여권번호",
    "passport_issue": "여권 발급일",
    "passport_expiry": "여권 유효기간",
    "address_kr": "국내 주소",
    "phone": "휴대전화",
    "email": "이메일",
    "address_home": "본국 주소",
    "bank_name": "거래은행",
    "bank_account": "계좌번호",
    "occupation": "직업",
    "workplace_name": "근무처명",
    "school_name": "학교명",
    "school_type": "학교종류",
}


def get_profile(persona_id_or_dict: str | dict) -> dict:
    """페르소나에서 프로필 규약 키만 뽑아 dict로 돌려준다.

    규약 4절대로 없는 키는 공란("")으로 채운다. 프로필 필드가 없는
    동적 페르소나를 넣어도 KeyError 없이 전 키가 공란으로 나온다.
    korean_name, nationality, visa_type은 중복 저장 금지 원칙에 따라
    기존 필드(name, country, visa)에서 유도해 채운다."""
    if isinstance(persona_id_or_dict, str):
        p = get_persona(persona_id_or_dict)
    else:
        p = persona_id_or_dict
    prof = {key: p.get(key, "") for key in PROFILE_FIELD_LABELS}
    prof["korean_name"] = p.get("name", "")
    prof["nationality"] = COUNTRY_NAME_EN.get(p.get("country", ""), "")
    visa = p.get("visa", "")
    prof["visa_type"] = VISA_TYPE_LABEL.get(visa, visa)
    return prof


def derive_profile_fields(
    persona_id_or_dict: str | dict,
    as_of: str = DEMO_TODAY_STR,
) -> dict:
    """PROFILE_CONTRACT 2절의 자동 유도 필드를 계산한다.

    프로필에 저장하지 않는 값이다. 신청서 작성 시점에 이 함수로 계산해 쓴다.

    반환 dict 키:
      birth_date    : str - 'YYYY.MM.DD'. reg_no 앞 6자리에서 유도.
                      reg_no가 없거나 형식이 다르면 "".
      enrolled      : str - '재학' | '비재학'. visa가 D-2면 재학.
      annual_income : int - monthly_wage_krw x 12 (근로자만. 무급이면 0).
      pay_country   : str - 지급상대국. nationality를 그대로 쓴다.
      apply_date    : str - 신청일. 기본은 데모 기준일(as_of 인자로 대체 가능).
    """
    if isinstance(persona_id_or_dict, str):
        p = get_persona(persona_id_or_dict)
    else:
        p = persona_id_or_dict

    # 생년월일 유도: reg_no 'YYMMDD-GXXXXXX'에서 앞 6자리.
    # 뒷자리 첫 숫자(G)가 7이나 8이면 2000년대 출생. 5나 6이면 1900년대 출생.
    reg = p.get("reg_no", "")
    birth_date = ""
    if len(reg) >= 8 and reg[:6].isdigit():
        century = "20" if reg[7] in "78" else "19"
        birth_date = f"{century}{reg[:2]}.{reg[2:4]}.{reg[4:6]}"

    enrolled = "재학" if p.get("visa") == "D-2" else "비재학"
    annual_income = p.get("monthly_wage_krw", 0) * 12
    pay_country = COUNTRY_NAME_EN.get(p.get("country", ""), "")

    return {
        "birth_date": birth_date,
        "enrolled": enrolled,
        "annual_income": annual_income,
        "pay_country": pay_country,
        "apply_date": as_of,
    }
