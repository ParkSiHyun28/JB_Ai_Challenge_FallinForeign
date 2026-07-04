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
        "social_security_treaty": False,  # 베트남 미체결 → 반환일시금 수령 가능
        "deposit_balance_krw": 0,
        "summary": "베트남 E-9 근로자. 출국 임박. 반환일시금과 출국만기보험 수령 대상.",
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
        "social_security_treaty": False,  # 네팔 미체결 → 귀국 시 반환일시금 불가
        "deposit_balance_krw": 20_000_000,  # 잔고증명 요건
        "summary": "네팔 D-2 유학생. Thin Filer. 잔고증명 예치금 보유. 대안신용 축적 대상.",
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
# app.py의 TODAY와 같은 값으로 둔다(순환 import를 피하려 여기 따로 정의).
DEMO_TODAY = (2026, 10)

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
    deposit = _round_man(rng.randint(15_000_000, 40_000_000)) if visa in ("D-2", "D-10", "F-2") else 0
    pid = f"{visa.lower().replace('-', '')}_{flag.lower()}_{seq:03d}"
    summary = f"{country} {visa} {role}. 입국 {entry_date}. " + (
        "반환일시금과 출국만기보험 대상." if visa == "E-9" else
        "잔고증명 예치금 보유. 대안신용 축적 대상." if deposit else "체류 현황 점검 대상."
    )
    return {
        "id": pid, "name": name, "name_en": name_en, "flag": flag, "country": country,
        "visa": visa, "role": role, "entry_date": entry_date, "exit_plan": exit_plan,
        "monthly_wage_krw": wage, "monthly_remit_krw": remit, "pension_months": pension,
        "social_security_treaty": False, "deposit_balance_krw": deposit, "summary": summary,
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
      expiry        : str  — 'YYYY-MM'. 비자 만료 연월.
      renewal_start : str  — 'YYYY-MM'. 갱신 신청 가능 시작 연월 (만료 4개월 전).
      months_left   : int  — 오늘(today) 기준 만료까지 남은 개월수.
                             양수=아직 남음. 0=이번 달 만료. 음수=이미 초과.
      renewal_needed: bool — True면 출국 전에 갱신이 필요함.
                             출국 예정일이 만료일보다 늦으면 True.
      status        : str  — 'ok' | 'renewal_window' | 'expired' | 'no_renewal'.
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
