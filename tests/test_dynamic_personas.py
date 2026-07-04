"""동적 페르소나 회귀 테스트.

50~100명을 무작위로 생성해 등록한 뒤 전 tool과 active_plan을 그 전원에 대해 호출해
예외가 없고 출력 4키 규약을 지키는지 검증한다. 고정 2명(minh suman) 테스트와 별개다.
이 파일은 동적화 작업이 깨지지 않게 지키는 안전망이다."""

from shared.personas import (
    PERSONAS, get_persona, all_personas, make_random_personas, register_personas,
    VISA_ROLE, DEMO_TODAY_STR,
)
from shared.registry import TOOL_REGISTRY
from backend.core import active_plan

DEMO_TODAY = DEMO_TODAY_STR
COUNT = 80
SEED = 7


def _make():
    """COUNT명을 만들어 등록하고 그 dict를 돌려준다."""
    ps = make_random_personas(COUNT, seed=SEED)
    register_personas(ps)
    return ps


def _run_tool(name, args):
    """as_of가 필요한 tool에 데모 기준일을 채워 호출한다."""
    func = TOOL_REGISTRY[name]
    kwargs = dict(args)
    if "as_of" in getattr(func, "__code__").co_varnames:
        kwargs["as_of"] = DEMO_TODAY
    return func(**kwargs)


def test_count_and_unique_ids():
    """COUNT명을 정확히 만들고 id가 고유하며 고정 2명과 겹치지 않는다."""
    ps = make_random_personas(COUNT, seed=1)
    assert len(ps) == COUNT
    ids = list(ps.keys())
    assert len(ids) == len(set(ids))
    assert "minh" not in ids and "suman" not in ids


def test_reproducible():
    """같은 seed면 같은 결과, 다른 seed면 다른 결과."""
    assert make_random_personas(COUNT, seed=1) == make_random_personas(COUNT, seed=1)
    assert make_random_personas(COUNT, seed=1) != make_random_personas(COUNT, seed=2)


def test_derived_field_consistency():
    """파생필드 일관성: visa-role 일치, wage 0이면 remit 0, exit가 entry보다 미래."""
    ps = make_random_personas(COUNT, seed=SEED)
    for p in ps.values():
        assert VISA_ROLE[p["visa"]] == p["role"]
        if p["monthly_wage_krw"] == 0:
            assert p["monthly_remit_krw"] == 0
        entry = tuple(map(int, p["entry_date"].split("-")))
        ex = tuple(map(int, p["exit_plan"].split("-")))
        assert ex > entry


def test_exit_after_demo_today():
    """모든 동적 페르소나의 출국 예정일이 데모 기준일 이후 미래다(C1 회귀 방지)."""
    ps = make_random_personas(COUNT, seed=SEED)
    for p in ps.values():
        ex = tuple(map(int, p["exit_plan"].split("-")))
        assert ex > (2026, 10)


def test_entry_before_demo_today():
    """모든 동적 페르소나의 입국일이 데모 기준일(2026-10) 이전이다(미래 입국 방지)."""
    # seed=42 (60명)와 다른 seed 몇 개로 함께 검증한다.
    for seed, count in [(42, 60), (SEED, COUNT), (99, 60), (123, 60)]:
        ps = make_random_personas(count, seed=seed)
        for p in ps.values():
            entry = tuple(map(int, p["entry_date"].split("-")))
            assert entry < (2026, 10), (
                f"seed={seed} {p['id']} 입국일 {p['entry_date']}이 기준일 이후입니다."
            )


def test_all_tools_no_exception_for_all_personas():
    """등록된 동적 페르소나 전원에 8개 tool을 호출해 예외가 없고 4키 규약을 지킨다."""
    ps = _make()
    for pid in ps:
        for name in TOOL_REGISTRY:
            out = _run_tool(name, {"persona_id": pid})
            assert isinstance(out, dict)
            for key in ("summary", "detail", "numbers", "card"):
                assert key in out, f"{name}({pid}) 4키 위반: {key} 없음"
            if out["card"] is not None:
                for key in ("icon", "head", "body", "metric"):
                    assert key in out["card"], f"{name}({pid}) card 키 위반: {key} 없음"


def test_active_plan_non_empty_and_runnable():
    """active_plan이 전원에 대해 빈 리스트가 아니고 실행해도 무예외다."""
    ps = _make()
    for pid in ps:
        plan = active_plan(pid)
        assert plan, f"{pid} 빈 plan"
        for name, args in plan:
            assert name in TOOL_REGISTRY
            _run_tool(name, args)


def test_no_negative_dday():
    """deadline_radar가 음수 D-day나 음수 보험금을 내지 않는다(C1 C2 회귀 방지)."""
    ps = _make()
    for pid in ps:
        p = get_persona(pid)
        if p["visa"] != "E-9":
            continue
        out = _run_tool("deadline_radar", {"persona_id": pid})
        assert out["numbers"]["days_to_exit"] >= 0
        assert out["numbers"]["severance_insurance_total_krw"] >= 0
