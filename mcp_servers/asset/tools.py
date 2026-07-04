"""자산 부문 tool 5개. 순수 함수다. MCP나 Claude를 모른다.
입력은 키워드 인자, 출력은 {summary, detail, numbers, card} dict."""

from datetime import date

from shared.personas import get_persona
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
    """국민연금 반환일시금 예상액을 산출한다. 사회보장협정 체결 여부를 반영한다.
    커버 자산종: 연금."""
    p = get_persona(persona_id)
    months = p["pension_months"]
    treaty = p["social_security_treaty"]
    # 협정 미체결(treaty False)이면 반환일시금 수령 대상. 단 납부월수 0이면 받을 게 없다.
    can_receive = (not treaty) and months > 0
    refund = months * data.PENSION_MONTHLY_REFUND_KRW
    numbers = {
        "pension_months": months,
        "treaty": treaty,
        "can_receive": can_receive,
        "estimated_refund_krw": refund,
    }
    if can_receive:
        return {
            "summary": f"{p['name']}님은 귀국 시 국민연금 반환일시금 약 {_won(refund)}을 받을 수 있습니다.",
            "detail": (
                f"{p['country']}은 한국과 사회보장협정이 미체결이라 {p['visa']} 근로자는 귀국 시 반환일시금 수령 대상입니다. "
                f"납부 {months}개월 기준 예상 수령액은 약 {_won(refund)}입니다. "
                f"2023년 외국인 반환일시금 총 지급액은 {data.PENSION_TOTAL_PAYOUT_2023_KRW/1e8:,.0f}억 원 규모입니다."
            ),
            "numbers": numbers,
            "card": {
                "icon": "",
                "head": f"귀국 시 반환일시금 약 {_won(refund)} 수령 가능",
                "body": f"납부 {months}개월치. 출국 후 청구하면 받습니다. 신청서 작성을 도와드립니다.",
                "metric": f"예상 수령 {_won(refund)}",
            },
        }
    # 수령 불가 (협정 미체결이지만 유학생이라 납부 이력 없음, 또는 협정 체결국)
    return {
        "summary": f"{p['name']}님은 귀국 시 국민연금 반환일시금을 받기 어렵습니다.",
        "detail": (
            f"{p['country']}은 한국과 사회보장협정이 미체결입니다. "
            f"현재 납부 이력({months}개월)으로는 귀국 시 반환일시금 수령이 어렵습니다. "
            f"단 취업비자(E-7)로 전환해 한국에 남으면 납부 이력이 수령으로 이어질 수 있습니다. "
            f"유학생 {data.STUDENT_JOB_HOPE_RATE*100:.1f}%가 한국 취업을 희망합니다. 취업전환율은 {data.STUDENT_VISA_CONVERT_RATE*100:.1f}%입니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": "귀국하면 연금 돌려받기 어렵습니다",
            "body": f"{p['country']}-한국 협정 미체결. 단 E-7 취업전환 시 납부 이력이 수령으로 이어집니다. 취업비자 전환 도움 필요하면 알려주세요.",
            "metric": f"취업전환 가능성 {data.STUDENT_VISA_CONVERT_RATE*100:.1f}%",
        },
    }


def remit_optimizer(persona_id: str) -> dict:
    """송금 수수료와 경로를 비교해 최저비용 경로를 안내한다.
    커버 자산종: 송금."""
    p = get_persona(persona_id)
    monthly = p["monthly_remit_krw"]
    routes = sorted(data.REMIT_ROUTES, key=lambda r: r["fee_rate"])
    best = routes[0]
    default = next(r for r in data.REMIT_ROUTES if r["name"] == "은행 한도제한계좌")
    saving = int((default["fee_rate"] - best["fee_rate"]) * monthly)
    numbers = {
        "monthly_remit_krw": monthly,
        "default_fee_rate": default["fee_rate"],
        "best_route": "WireBarley" if best["name"] == "WireBarley" else best["name"],
        "best_fee_rate": best["fee_rate"],
        "monthly_saving_krw": saving,
        "annual_saving_krw": saving * 12,
    }
    if monthly == 0:
        return {
            "summary": f"{p['name']}님은 정기 송금 내역이 없어 경로 비교가 필요하지 않습니다.",
            "detail": "송금 발생 시 최저비용 경로를 다시 안내합니다.",
            "numbers": numbers,
            "card": None,
        }
    return {
        "summary": f"송금 경로를 {best['name']}로 바꾸면 매달 {_won(saving)}을 아낍니다.",
        "detail": (
            f"현재 은행 한도제한계좌 경로는 수수료율 {default['fee_rate']*100:.2f}%입니다. "
            f"{best['name']} 경로는 {best['fee_rate']*100:.1f}%입니다. "
            f"월 송금 {_won(monthly)} 기준 매달 {_won(saving)}, 연간 약 {_won(saving*12)}을 절감합니다."
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": "송금 비용 절반으로 줄일 수 있습니다",
            "body": f"현재 경로({default['fee_rate']*100:.2f}%) 대신 {best['name']}({best['fee_rate']*100:.1f}%)를 쓰면 매달 {_won(saving)} 아낍니다. 연간 약 {_won(saving*12)} 절감.",
            "metric": f"경로 {len(data.REMIT_ROUTES)}개 비교 완료",
        },
    }


def credit_builder(persona_id: str, months_accrued: int = 0) -> dict:
    """월세와 통신비와 공과금을 대안신용 데이터로 축적한다. 축적 개월 기준 프로필 형성도를 추정한다.
    커버 자산종: 신용."""
    p = get_persona(persona_id)
    months_accrued = max(0, months_accrued)
    started = months_accrued >= data.CREDIT_PROFILE_MIN_MONTHS
    complete = months_accrued >= data.CREDIT_PROFILE_FULL_MONTHS
    numbers = {
        "months_accrued": months_accrued,
        "min_months": data.CREDIT_PROFILE_MIN_MONTHS,
        "full_months": data.CREDIT_PROFILE_FULL_MONTHS,
        "profile_started": started,
        "profile_complete": complete,
    }
    if complete:
        head = f"{months_accrued}개월 납부 이력으로 신용 프로필 완성"
        body = "JB 외국인 전용 대출과 카드 심사에 바로 활용 가능합니다. 취업 후 신용대출도 준비됩니다."
        metric = f"대안신용 데이터 {months_accrued}개월치"
    elif started:
        head = "대안신용 등급 형성 시작"
        body = f"{months_accrued}개월 납부 이력 축적. {data.CREDIT_PROFILE_FULL_MONTHS}개월 도달 시 프로필 완성됩니다."
        metric = f"신용데이터 {months_accrued}개월치"
    else:
        head = "오늘부터 신용 쌓기 시작"
        body = f"월세와 통신비 납부 이력을 신용데이터로 연동했습니다. {data.CREDIT_PROFILE_MIN_MONTHS}개월 후 JB 대출 심사에서 활용됩니다."
        metric = "신용데이터 연동 완료"
    return {
        "summary": f"{p['name']}님의 월세와 통신비 납부 이력을 대안신용으로 축적합니다.",
        "detail": (
            f"{p['name']}님은 소득이 적어 신용이력이 거의 없는 Thin Filer입니다. "
            f"월세와 통신비와 공과금을 KCB 마이데이터로 연동해 대안신용 데이터로 축적합니다. "
            f"현재 {months_accrued}개월 축적. {data.CREDIT_PROFILE_MIN_MONTHS}개월 이상이면 JB 외국인 전용 신용평가에 활용할 수 있습니다."
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
            f"소멸시효는 출국일로부터 {data.CLAIM_DEADLINE_YEARS}년이지만 청구를 모르면 소멸 위험이 있습니다. "
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
