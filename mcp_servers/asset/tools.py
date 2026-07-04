"""자산 부문 tool 5개. 순수 함수다. MCP나 Claude를 모른다.
입력은 키워드 인자, 출력은 {summary, detail, numbers, card} dict.

원칙 (2026-07 고도화):
- persona_id 문자열로 분기하지 않는다. 페르소나 필드(visa, flag, 금액, 날짜)로만 판정한다.
- 모든 수치는 data.py 상수 × 페르소나 값의 결정적 계산이다. 추정 단가나 고정 문구로
  수치를 만들지 않는다.
- 판정 근거가 없으면(테이블에 없는 국가 등) 추측하지 않고 정직하게 보류를 안내한다.
"""

from datetime import date

from shared.personas import get_persona, DEMO_TODAY
from mcp_servers.asset import data


def _won(n: int) -> str:
    """원화 정수를 자연스러운 한국어 금액 문자열로.
    만 원 미만은 '원', 만 원 이상은 '만 원', 억 이상은 '억 ...만 원'으로 적는다.
    만 원 미만 자투리(천원대)가 있으면 함께 표기해 정확도를 지킨다.
    영어식 '백만/천만' 표기나 raw 자릿수 나열('29,700,000원')을 피한다.
    예: 5000 -> '5,000원', 35_500 -> '3만 5,500원', 29_700_000 -> '2,970만 원',
        129_700_000 -> '1억 2,970만 원'."""
    n = int(round(n))
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 10_000:
        return f"{sign}{n:,}원"
    eok, rem = divmod(n, 100_000_000)  # 억
    man = rem // 10_000                 # 만
    won = rem % 10_000                  # 만 원 미만 자투리
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    head = " ".join(parts)
    # 만 원 미만 자투리: 억 단위 큰 금액에선 무시(노이즈), 1억 미만에선 살린다.
    if won and not eok:
        return f"{sign}{head} {won:,}원"
    return f"{sign}{head} 원"


# ---------------------------------------------------------------------------
# 연월(YYYY-MM) 계산 도우미
# ---------------------------------------------------------------------------

def _ym(s: str) -> tuple:
    """'YYYY-MM' 문자열을 (연, 월) 튜플로."""
    y, m = map(int, s.split("-"))
    return y, m


def _ym_add(t: tuple, delta: int) -> tuple:
    """(연, 월)에 delta개월을 더한다."""
    total = t[0] * 12 + (t[1] - 1) + delta
    y, m0 = divmod(total, 12)
    return y, m0 + 1


def _ym_diff(a: tuple, b: tuple) -> int:
    """b - a 개월수."""
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def _ym_str(t: tuple) -> str:
    return f"{t[0]:04d}-{t[1]:02d}"


def collateral_calc(persona_id: str) -> dict:
    """잔고증명 예치금 기준 예금담보대출 한도(95%)를 산출한다.
    커버 자산종: 예금, 대출."""
    p = get_persona(persona_id)
    deposit = p["deposit_balance_krw"]
    limit = int(round(deposit * data.COLLATERAL_LOAN_RATIO / 10_000) * 10_000)
    numbers = {
        "deposit_krw": deposit,
        "loan_ratio": data.COLLATERAL_LOAN_RATIO,
        "loan_limit_krw": limit,
    }
    if deposit == 0:
        return {
            "summary": f"{p['name']}님은 잔고증명 예치금이 없어 예금담보대출 대상이 아닙니다.",
            "detail": "예금담보대출은 잔고증명 예치금을 담보로 합니다. 현재 예치금이 없습니다.",
            "numbers": numbers,
            "card": None,
        }
    return {
        "summary": f"잔고 {_won(deposit)}을 유지하면서 예금담보대출로 {_won(limit)}까지 활용할 수 있습니다.",
        "detail": (
            f"잔고증명 예치금 {_won(deposit)} 유지가 비자 체류 요건입니다. "
            f"직접 인출하면 비자 요건을 위반합니다. 대신 예금담보대출(한도 {int(data.COLLATERAL_LOAN_RATIO*100)}%)로 "
            f"{_won(limit)}까지 생활비를 마련하면 잔고 요건 위반 없이 안전합니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"잔고 {_won(deposit)} 유지하며 {_won(limit)} 활용 가능",
            "body": f"예금담보대출(한도 {int(data.COLLATERAL_LOAN_RATIO*100)}%)로 생활비 마련 가능. 잔고 요건 위반 없이 안전하게 쓸 수 있습니다.",
            "metric": f"담보대출 한도 {_won(limit)}",
        },
    }


def pension_estimator(persona_id: str) -> dict:
    """국민연금 반환일시금을 판정하고 예상 수령액을 공단 공식으로 계산한다.
    공식: 납부한 연금보험료(사용자 부담 포함) + 이자(3년 만기 정기예금이자율 월할 단리).
    근거: 국민연금법 제77조. 판정은 data.NPS_ELIGIBILITY 국가 테이블 + E-9/H-2 특례.
    전면 스토리는 '매달 떼여 온 보험료 돌려받기'다. 협정 용어는 화면에 내세우지 않는다.
    커버 자산종: 연금."""
    p = get_persona(persona_id)
    name = p["name"]
    months = p["pension_months"]
    flag = p.get("flag", "")
    elig = data.NPS_ELIGIBILITY.get(flag)

    # --- 판정. 전부 페르소나 필드와 국가 테이블 기반. 추측 금지 ---
    if elig is None:
        # 판정 정보가 없는 국가. 틀린 답 대신 정직한 보류.
        return {
            "summary": f"{name}님 국적의 반환일시금 판정 기준이 아직 등록되지 않았습니다.",
            "detail": (
                f"{p['country']} 국적의 국민연금 반환일시금 수령 기준이 시스템에 등록되지 않았습니다. "
                "정확하지 않은 안내를 드리지 않기 위해 판정을 보류합니다. "
                "국민연금공단(국번 없이 1355)에서 확인할 수 있습니다."
            ),
            "numbers": {"eligible": None, "reason": "unknown_country", "pension_months": months},
            "card": None,
        }

    if not elig["enrolled"]:
        # 가입 제외국: 보험료 공제 자체가 없어 돌려받을 연금도 없다 (예: 네팔, 미얀마, 방글라데시).
        return {
            "summary": f"{name}님은 국민연금 대상이 아니라서 돌려받을 연금이 없습니다.",
            "detail": (
                f"{p['country']} 국적은 현행 기준으로 국민연금 가입 대상이 아닙니다. "
                "월급이나 소득에서 연금 보험료가 공제되지 않으므로 귀국할 때 돌려받을 연금도 없습니다. "
                "대신 통신비와 공과금 납부 이력으로 신용을 쌓아 두면 한국 생활에 더 유리합니다."
            ),
            "numbers": {"eligible": False, "reason": "not_enrolled", "pension_months": months},
            "card": None,
        }

    if months <= 0:
        return {
            "summary": f"{name}님은 아직 국민연금 납부 이력이 없습니다.",
            "detail": (
                "국민연금 납부 이력이 없어 반환일시금 대상이 아닙니다. "
                "취업해 보험료를 납부하기 시작하면 그때부터 반환일시금이 쌓입니다."
            ),
            "numbers": {"eligible": False, "reason": "no_contribution", "pension_months": 0},
            "card": None,
        }

    # 수령 근거 판정 (특례 우선 → 국적 기준)
    basis = None
    basis_msg = ""
    if p["visa"] in data.NPS_SPECIAL_VISAS and elig["e9_h2"]:
        basis = "visa_special"
        basis_msg = f"{p['visa']} 근로자는 국적과 관계없이 반환일시금 수령 대상입니다."
    elif elig["national"] and months >= elig.get("min_months", 0):
        basis = "national"
        basis_msg = f"{p['country']} 국적은 귀국 시 반환일시금 수령이 보장됩니다."
    elif elig["national"]:
        short = elig["min_months"] - months
        return {
            "summary": f"{name}님은 납부 기간이 짧아 아직 반환일시금 조건에 못 미칩니다.",
            "detail": (
                f"{p['country']} 국적은 납부 {elig['min_months']}개월 이상부터 반환일시금을 받을 수 있습니다. "
                f"현재 {months}개월이라 {short}개월 부족합니다. 계속 납부하면 조건을 채울 수 있습니다."
            ),
            "numbers": {"eligible": False, "reason": "below_min_months",
                        "pension_months": months, "min_months": elig["min_months"]},
            "card": None,
        }
    else:
        return {
            "summary": f"{name}님은 귀국 시점 반환일시금 수령이 어렵습니다.",
            "detail": (
                f"{p['country']} 국적은 현행 기준으로 귀국 시 일시금 수령 대상이 아닙니다. "
                "납부한 보험료의 처리 방식은 개인별 상황에 따라 달라 국민연금공단(1355) 확인이 필요합니다."
            ),
            "numbers": {"eligible": False, "reason": "not_payable", "pension_months": months},
            "card": None,
        }

    # --- 계산. 공단 공식: 납부보험료(사용자 부담 포함) + 이자 ---
    # 월급을 기준소득월액 상하한으로 자른다. 상하한은 현행(2026-07~) 값을 전 기간에
    # 일괄 적용하는 근사다(연도별 상하한 이력 미적용. 주석으로 한계 명시).
    wage = min(max(p["monthly_wage_krw"], data.NPS_INCOME_MIN_KRW), data.NPS_INCOME_MAX_KRW)
    entry = _ym(p["entry_date"])
    exit_ = _ym(p["exit_plan"])
    principal = 0.0
    interest = 0.0
    for i in range(months):
        y, m = _ym_add(entry, i)
        contrib = wage * data.nps_rate_for_year(y)  # 연도별 요율(2025까지 9%, 2026부터 인상)
        principal += contrib
        # 이자: 낸 달의 다음 달부터 지급사유(출국) 발생월까지 월할 단리
        hold = _ym_diff((y, m), exit_)
        if hold > 0:
            interest += contrib * data.NPS_INTEREST_RATE * (hold / 12)
    principal = int(round(principal))
    interest = int(round(interest))
    total = principal + interest
    # 표시용 반올림(만 원 단위). '약'과 원 단위 정밀 표기가 어긋나지 않게 한다.
    # numbers에는 정밀값을 그대로 둔다.
    disp_total = int(round(total / 10_000) * 10_000)
    disp_principal = int(round(principal / 10_000) * 10_000)
    disp_interest = int(round(interest / 10_000) * 10_000)
    # '매달 떼여 온 돈' 표시용: 마지막 납부월 요율 기준 본인 부담분(절반)
    last_y = _ym_add(entry, months - 1)[0]
    my_monthly = int(round(wage * data.nps_rate_for_year(last_y) / 2))

    numbers = {
        "eligible": True,
        "basis": basis,
        "pension_months": months,
        "wage_base_krw": wage,
        "monthly_deduction_krw": my_monthly,
        "principal_krw": principal,
        "interest_krw": interest,
        "estimated_refund_krw": total,
        "deadline_years": data.PENSION_REFUND_DEADLINE_YEARS,
    }
    return {
        "summary": f"{name}님은 귀국 시 반환일시금 약 {_won(disp_total)}을 받을 수 있습니다.",
        "detail": (
            f"매달 월급에서 본인 부담 연금 보험료 약 {_won(my_monthly)}이 공제돼 왔고 회사도 같은 금액을 부담했습니다. "
            f"{basis_msg} 납부 {months}개월 기준 원금 약 {_won(disp_principal)}에 이자 약 {_won(disp_interest)}을 더해 "
            f"약 {_won(disp_total)}을 돌려받습니다. "
            f"청구 시효는 출국 후 {data.PENSION_REFUND_DEADLINE_YEARS}년입니다(국민연금법 제115조). "
            f"2023년 외국인 반환일시금 총 지급액은 {data.PENSION_TOTAL_PAYOUT_2023_KRW/1e8:,.0f}억 원 규모입니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"귀국 시 약 {_won(disp_total)} 돌려받습니다",
            "body": (
                f"매달 낸 연금 보험료와 회사 부담분에 이자를 더한 금액입니다. "
                f"출국 후 {data.PENSION_REFUND_DEADLINE_YEARS}년 안에 청구해야 합니다. 신청서 작성을 도와드립니다."
            ),
            "metric": f"예상 수령 {_won(disp_total)}",
        },
    }


def remit_optimizer(persona_id: str) -> dict:
    """송금 경로별 진짜 총비용(고정수수료 + 부가비용 + 환율마진)을 비교해
    최저 경로와 귀국 전 총 절감액을 계산한다. 커버 자산종: 송금."""
    p = get_persona(persona_id)
    name = p["name"]
    monthly = p["monthly_remit_krw"]
    if monthly == 0:
        return {
            "summary": f"{name}님은 정기 송금 내역이 없어 경로 비교가 필요하지 않습니다.",
            "detail": "송금 발생 시 최저비용 경로를 다시 안내합니다.",
            "numbers": {"monthly_remit_krw": 0},
            "card": None,
        }

    def route_cost(r: dict) -> int:
        return r["fixed_fee_krw"] + r["extra_fee_krw"] + int(round(r["spread_rate"] * monthly))

    table = [
        {"id": r["id"], "name": r["name"], "monthly_cost_krw": route_cost(r),
         "spread_rate": r["spread_rate"]}
        for r in data.REMIT_ROUTES_TC
    ]
    best = min(table, key=lambda t: t["monthly_cost_krw"])
    # 현재 경로: 페르소나 필드. 값이 없거나 목록에 없으면 은행 창구로 간주한다(보수적 기본).
    cur_id = p.get("remit_route") or "bank_counter"
    current = next((t for t in table if t["id"] == cur_id), table[0])
    saving = current["monthly_cost_krw"] - best["monthly_cost_krw"]
    # 귀국까지 남은 개월 × 월 절감 = 귀국 전 총 절감 (페르소나 exit_plan 연동)
    months_left = max(0, _ym_diff(DEMO_TODAY, _ym(p["exit_plan"])))
    total_saving = saving * months_left

    numbers = {
        "monthly_remit_krw": monthly,
        "current_route": current["id"],
        "current_cost_krw": current["monthly_cost_krw"],
        "best_route": best["id"],
        "best_cost_krw": best["monthly_cost_krw"],
        "monthly_saving_krw": saving,
        "months_to_exit": months_left,
        "total_saving_until_exit_krw": total_saving,
        "cost_table": table,
    }

    # 수취 통화 표기(표기 전용. 계산에 쓰지 않음)
    fx = data.FX_DISPLAY.get(p.get("flag", ""))
    fx_note = ""
    if fx:
        cur_name, per_krw = fx
        fx_note = f" 매달 보내는 {_won(monthly)}은 현지 수취 기준 약 {monthly * per_krw:,.0f} {cur_name}입니다."
    # 네팔은 국제 통계(RPW) 미조사 통로라 비용 추정의 한계를 정직하게 밝힌다.
    basis_note = " 네팔 송금 비용은 국제 통계 미조사 통로라 베트남 기준을 준용한 추정입니다." if p.get("flag") == "NP" else ""

    if saving <= 0:
        return {
            "summary": f"{name}님은 이미 가장 저렴한 송금 경로({current['name']})를 쓰고 있습니다.",
            "detail": (
                f"현재 경로의 월 총비용은 {_won(current['monthly_cost_krw'])}입니다. "
                f"비교한 {len(table)}개 경로 중 최저입니다.{fx_note}{basis_note}"
            ),
            "numbers": numbers,
            "card": {
                "icon": "",
                "head": "이미 최저비용 경로를 쓰고 있습니다",
                "body": f"월 총비용 {_won(current['monthly_cost_krw'])}. 경로 {len(table)}개 비교 결과 현재 경로가 최저입니다.",
                "metric": f"경로 {len(table)}개 비교 완료",
            },
        }

    return {
        "summary": f"송금 경로를 바꾸면 귀국 전까지 총 {_won(total_saving)}을 아낄 수 있습니다.",
        "detail": (
            f"지금 쓰는 {current['name']}의 진짜 비용은 월 {_won(current['monthly_cost_krw'])}입니다. "
            f"표시 수수료 외에 환율에 숨은 마진(약 {current['spread_rate']*100:.1f}%)이 붙기 때문입니다. "
            f"{best['name']}(환율마진 약 {best['spread_rate']*100:.1f}%)로 바꾸면 월 {_won(best['monthly_cost_krw'])}으로 줄어 "
            f"매달 {_won(saving)}을 아낍니다. 귀국 예정({p['exit_plan']})까지 {months_left}개월 동안 "
            f"총 {_won(total_saving)} 절감입니다.{fx_note}{basis_note}"
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"송금 비용을 매달 {_won(saving)} 줄일 수 있습니다",
            "body": (
                f"{current['name']} 대신 {best['name']}를 쓰면 됩니다. "
                f"귀국까지 {months_left}개월이면 총 {_won(total_saving)}입니다."
            ),
            "metric": f"귀국 전 총 절감 {_won(total_saving)}",
        },
    }


def credit_builder(persona_id: str) -> dict:
    """통신비와 공과금(현행 반영)과 월세(JB 제안 모델) 납부 이력의 대안신용 축적
    단계를 계산한다. 축적 개월은 페르소나 credit_accrual_start에서 도출한다(고정값 금지).
    단계 기준은 KCB 확인치(연속 12개월 최소 가점, 36개월 최대). 커버 자산종: 신용."""
    p = get_persona(persona_id)
    name = p["name"]
    start = p.get("credit_accrual_start")
    months = max(0, _ym_diff(_ym(start), DEMO_TODAY)) if start else 0

    min_step = data.CREDIT_LADDER[0]   # 12개월
    max_step = data.CREDIT_LADDER[-1]  # 36개월
    reached_min = months >= min_step["months"]
    reached_max = months >= max_step["months"]
    next_step = None if reached_max else (max_step if reached_min else min_step)
    months_to_next = (next_step["months"] - months) if next_step else 0
    # 다음 단계 도달 예정 연월: 축적 시작월 + 필요 개월. 미시작이면 오늘 시작 가정.
    base = _ym(start) if start else DEMO_TODAY
    next_ym = _ym_str(_ym_add(base, next_step["months"])) if next_step else ""

    numbers = {
        "months_accrued": months,
        "accrual_start": start,
        "min_months": min_step["months"],
        "max_months": max_step["months"],
        "reached_min": reached_min,
        "reached_max": reached_max,
        "months_to_next": months_to_next,
        "next_step_ym": next_ym,
        "items_official": list(data.CREDIT_ITEMS_OFFICIAL),
        "items_proposed": list(data.CREDIT_ITEMS_PROPOSED),
    }

    if reached_max:
        head = f"최대 가점 조건({max_step['months']}개월) 충족"
        body = "연체 없는 납부 이력이 최대 가점 조건을 채웠습니다. JB 외국인 금융상품 심사에 바로 활용할 수 있습니다."
        metric = f"축적 {months}개월째"
    elif reached_min:
        head = f"가점 반영선({min_step['months']}개월) 통과. {months}개월째 축적 중"
        body = f"최대 가점({max_step['months']}개월)까지 {months_to_next}개월 남았습니다. {next_ym} 도달 예정입니다."
        metric = f"축적 {months}개월째"
    elif months > 0:
        head = f"신용 이력 {months}개월째 축적 중"
        body = f"가점 반영 최소선({min_step['months']}개월)까지 {months_to_next}개월. {next_ym}부터 반영이 시작됩니다."
        metric = f"축적 {months}개월째"
    else:
        head = "오늘부터 신용 쌓기 시작"
        body = f"통신비와 공과금 납부 이력을 연동하면 {min_step['months']}개월 뒤인 {next_ym}부터 가점에 반영됩니다."
        metric = "신용데이터 연동 시작"

    if months > 0:
        summary = f"{name}님의 납부 이력 {months}개월이 대안신용으로 쌓이고 있습니다."
    else:
        summary = f"{name}님의 통신비와 공과금 납부 이력을 대안신용으로 연동할 수 있습니다."

    return {
        "summary": summary,
        "detail": (
            f"{name}님은 금융 이력이 부족한 Thin Filer입니다. "
            f"현행 신용평가(KCB)는 {'와 '.join(data.CREDIT_ITEMS_OFFICIAL[:2])} 등 납부 이력을 등록하면 "
            f"가점을 줍니다(비금융 비중 {data.CREDIT_KCB_NONFIN_WEIGHT*100:.0f}%). "
            f"연체 없는 연속 {min_step['months']}개월부터 반영되고 {max_step['months']}개월에 최대가 됩니다. "
            f"월세 이력 반영은 아직 제도권에 없어 JB 제안 모델로 함께 축적합니다. "
            f"{data.CREDIT_EQUAL_NOTE}이라 통신 데이터 기반 평가 근거는 갖춰져 있습니다. "
            f"현재 {months}개월 축적입니다."
        ),
        "numbers": numbers,
        "card": {"icon": "", "head": head, "body": body, "metric": metric},
    }


def _months_to_severance(p: dict, as_of: date) -> int:
    """입국일부터 기준일까지 개월 수. 출국만기보험 적립 개월 추정."""
    entry_y, entry_m = map(int, p["entry_date"].split("-"))
    return (as_of.year - entry_y) * 12 + (as_of.month - entry_m)


def deadline_radar(persona_id: str, as_of: str) -> dict:
    """반환일시금과 출국만기보험 청구 마감 D-Day를 추적한다.
    as_of는 기준일 'YYYY-MM-DD' 문자열. 커버 자산종: 연금, 보험."""
    p = get_persona(persona_id)
    today = date.fromisoformat(as_of)
    exit_y, exit_m = map(int, p["exit_plan"].split("-"))
    exit_date = date(exit_y, exit_m, 1)
    days_to_exit = (exit_date - today).days
    # 출국 예정일이 지난 페르소나는 음수 D-day가 나온다. 표시용 라벨로 음수 노출을 막는다.
    # 동적 생성기는 항상 미래 출국을 보장하지만 임의 페르소나 대비 방어한다.
    dday_label = f"D-{days_to_exit}" if days_to_exit >= 0 else "출국 예정일 경과"
    # E-9 근로자만 출국만기보험 대상 (월 통상임금 8.3% 적립)
    has_insurance = p["visa"] == "E-9"
    insurance_total = 0
    if has_insurance:
        months = max(0, _months_to_severance(p, today))
        insurance_total = max(0, int(p["monthly_wage_krw"] * data.SEVERANCE_INSURANCE_RATE * months))
    numbers = {
        "as_of": as_of,
        "exit_plan": p["exit_plan"],
        "days_to_exit": days_to_exit,
        "has_severance_insurance": has_insurance,
        "severance_insurance_total_krw": insurance_total,
        "claim_deadline_years": data.CLAIM_DEADLINE_YEARS,
        "pension_refund_deadline_years": data.PENSION_REFUND_DEADLINE_YEARS,
    }
    if not has_insurance:
        return {
            "summary": f"{p['name']}님은 출국만기보험 대상이 아닙니다. 출국까지 {dday_label}.",
            "detail": (
                f"출국만기보험은 E-9 사업장 근로자 의무 가입 대상입니다. "
                f"{p['visa']} 비자는 해당하지 않습니다. 출국 예정일은 {p['exit_plan']}이고 현재 {dday_label}입니다."
            ),
            "numbers": numbers,
            "card": None,
        }
    return {
        "summary": f"출국만기보험 약 {_won(insurance_total)} 적립 중. 출국까지 {dday_label}, 청구 마감 소멸시효 {data.CLAIM_DEADLINE_YEARS}년.",
        "detail": (
            f"E-9 사업장은 출국만기보험 의무 가입 대상입니다. 월 통상임금의 {data.SEVERANCE_INSURANCE_RATE*100:.1f}%가 적립됩니다. "
            f"현재까지 약 {_won(insurance_total)} 적립 추정. 출국 예정일 {p['exit_plan']} 기준 {dday_label}입니다. "
            f"출국만기보험 청구 소멸시효는 출국(지급사유 발생일)부터 {data.CLAIM_DEADLINE_YEARS}년이지만 청구를 모르면 소멸 위험이 있습니다. "
            f"국민연금 반환일시금 시효는 출국 후 {data.PENSION_REFUND_DEADLINE_YEARS}년입니다. "
            f"참고로 미청구 휴면보험금은 {data.UNCLAIMED_INSURANCE_KRW/1e8:,.1f}억 원 규모이고 반환율은 {data.UNCLAIMED_RETURN_RATE*100:.0f}%에 그칩니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"출국만기보험 약 {_won(insurance_total)} 적립 중",
            "body": f"출국 후 {data.CLAIM_DEADLINE_YEARS}년 내 청구 필수. 지금 수령 절차를 미리 확인하세요.",
            "metric": f"출국까지 {dday_label}",
        },
    }


# tool 레지스트리. server.py와 app.py가 이 목록으로 tool을 등록한다.
TOOL_REGISTRY = {
    "deadline_radar": deadline_radar,
    "pension_estimator": pension_estimator,
    "collateral_calc": collateral_calc,
    "remit_optimizer": remit_optimizer,
    "credit_builder": credit_builder,
}

# 능동 모드에서 먼저 호출하는 트리거 tool (호출 순서)
ACTIVE_TOOLS = ["deadline_radar", "remit_optimizer"]
