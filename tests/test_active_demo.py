"""능동 점검 데모 회귀 테스트.

목적: 능동 모드가 두 페르소나 모두에게 채워진 카드를 보여줘야 한다.
배경: 이전에는 수만(D-2) 능동 모드가 deadline_radar와 remit_optimizer 카드 None으로
회색 info 박스만 떠 화면이 절반 비었다. active_plan이 페르소나별 tool을
고르게 바꿔 두 페르소나 모두 카드가 채워지게 했다. 이 불변식을 고정한다.

과거에는 streamlit app.py를 import할 수 없어 plan을 복제해 검증했다.
지금은 backend.core를 그대로 import할 수 있으므로 실물 active_plan을 직접 검증한다.
(복제본은 core와 어긋난 채 통과하는 사고가 있어 제거했다.)
"""

from backend.core import active_plan, run_tool


def _plans():
    return {pid: active_plan(pid) for pid in ("minh", "suman")}


def test_active_plan_tools_all_registered():
    """능동 plan이 부르는 tool이 전부 레지스트리에 있어야 한다.
    run_tool이 미등록 tool이면 RuntimeError를 내므로 실행 자체가 검증이다."""
    from shared.registry import TOOL_REGISTRY

    for persona_id, plan in _plans().items():
        for name, _ in plan:
            assert name in TOOL_REGISTRY, f"{persona_id} plan의 {name}이 레지스트리에 없다."


def test_active_plan_fills_cards_for_both_personas():
    """두 페르소나 모두 능동 모드에서 카드가 최소 3개 채워져야 한다.
    카드 None(회색 info 박스)은 데모에서 화면을 비우므로 카메라에 약하다."""
    for persona_id, plan in _plans().items():
        cards = 0
        for name, args in plan:
            out = run_tool(name, args)
            if out.get("card") is not None:
                cards += 1
        assert cards >= 3, f"{persona_id} 능동 모드 카드가 {cards}개뿐이다. 3개 이상이어야 데모가 일관된다."


def test_suman_active_plan_has_no_null_cards():
    """수만은 과거에 카드가 비어 화면이 절반 비었다. plan 전체가 카드를 채워야 한다."""
    nulls = []
    for name, args in active_plan("suman"):
        out = run_tool(name, args)
        if out.get("card") is None:
            nulls.append(name)
    assert not nulls, f"수만 능동 plan에 카드 None인 tool이 있다: {nulls}"
