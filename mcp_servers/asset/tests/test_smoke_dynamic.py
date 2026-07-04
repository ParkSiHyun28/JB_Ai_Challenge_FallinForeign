"""동적 페르소나 대량 스모크 테스트.

목적: "누가 와도 안 깨지고 거짓말 안 함"을 증명한다.
- 무작위 60명 × 자산 tool 5개 = 300회 실행. 예외 없음.
- 출력 4키 규약 준수. numbers는 dict. card는 None이거나 4키 dict.
- 수치 정합성: 음수 금액 없음, 모순 없음.
- 국가 판정 정합성: 가입 제외국은 연금 수령 불가.
"""

import pytest

from shared.personas import make_random_personas, register_personas
from mcp_servers.asset import tools, data

REQUIRED = {"summary", "detail", "numbers", "card"}
CARD_KEYS = {"icon", "head", "body", "metric"}


@pytest.fixture(scope="module")
def dyn_ids():
    people = make_random_personas(60, seed=42)
    register_personas(people)
    return list(people.keys())


def _call(name, pid):
    if name == "deadline_radar":
        return tools.deadline_radar(pid, as_of=data_today())
    return tools.TOOL_REGISTRY[name](pid)


def data_today():
    from shared.personas import DEMO_TODAY_STR
    return DEMO_TODAY_STR


def test_all_tools_all_dynamic_personas_follow_contract(dyn_ids):
    for pid in dyn_ids:
        for name in tools.TOOL_REGISTRY:
            out = _call(name, pid)
            label = f"{name}({pid})"
            assert isinstance(out, dict), f"{label}: dict 반환"
            assert REQUIRED <= set(out.keys()), f"{label}: 4키 누락 {set(out.keys())}"
            assert isinstance(out["numbers"], dict), f"{label}: numbers dict"
            card = out["card"]
            assert card is None or set(card.keys()) == CARD_KEYS, f"{label}: card 키 위반"


def test_no_negative_money_in_numbers(dyn_ids):
    """금액 계열(krw) 값은 음수가 나오면 안 된다."""
    for pid in dyn_ids:
        for name in tools.TOOL_REGISTRY:
            out = _call(name, pid)
            for k, v in out["numbers"].items():
                if k.endswith("_krw") and isinstance(v, (int, float)):
                    assert v >= 0, f"{name}({pid}) {k}={v} 음수"


def test_pension_excluded_countries_never_receive(dyn_ids):
    """가입 제외국(NP MM BD) 페르소나는 연금 수령 가능이 True로 나오면 안 된다."""
    from shared.personas import get_persona
    for pid in dyn_ids:
        p = get_persona(pid)
        if p["flag"] in ("NP", "MM", "BD"):
            out = tools.pension_estimator(pid)
            assert out["numbers"].get("eligible") is not True, f"{pid}: 제외국인데 수령 가능"


def test_pension_e9_with_contribution_receives(dyn_ids):
    """E-9 + 납부월수 있으면 특례로 수령 가능해야 한다(가입 제외국 제외)."""
    from shared.personas import get_persona
    for pid in dyn_ids:
        p = get_persona(pid)
        if p["visa"] == "E-9" and p["pension_months"] > 0 and p["flag"] not in ("NP", "MM", "BD"):
            out = tools.pension_estimator(pid)
            assert out["numbers"].get("eligible") is True, f"{pid}: E-9 납부자인데 수령 불가"
            assert out["numbers"]["estimated_refund_krw"] > 0


def test_remit_saving_never_negative(dyn_ids):
    """송금 절감액은 음수가 될 수 없다(현재 경로가 최저면 0)."""
    for pid in dyn_ids:
        out = tools.remit_optimizer(pid)
        assert out["numbers"].get("monthly_saving_krw", 0) >= 0, f"{pid}: 절감액 음수"


def test_all_twelve_countries_have_eligibility_row():
    """동적 생성기 국가 풀 12개국이 모두 판정 테이블에 있어야 한다."""
    flags = set()
    for pool in [("VN", "TH", "ID", "KH", "MM", "NP", "PH"),
                 ("NP", "VN", "BD", "IN", "UZ", "CN"),
                 ("VN", "ID", "NP", "MN"),
                 ("VN", "CN", "PH", "TH")]:
        flags.update(pool)
    for f in flags:
        assert f in data.NPS_ELIGIBILITY, f"{f} 판정 테이블 누락"
