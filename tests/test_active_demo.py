"""능동 점검 데모 회귀 테스트.

목적: 능동 모드가 두 페르소나 모두에게 채워진 카드를 보여줘야 한다.
배경: 이전에는 수만(D-2) 능동 모드가 deadline_radar와 remit_optimizer 카드 None으로
회색 info 박스만 떠 화면이 절반 비었다. app.py의 active_plan이 페르소나별 tool을
고르게 바꿔 두 페르소나 모두 카드가 채워지게 했다. 이 불변식을 고정한다.

app.py는 streamlit 런타임을 import 시점에 건드려 단위 테스트에서 직접 import하기 까다롭다.
그래서 active_plan의 계약(페르소나별 tool과 인자)을 여기 복제해, 그 tool들이 실제로
카드를 만드는지 검증한다. app.py의 plan과 이 복제본이 어긋나면 데모가 깨진 것이므로
이 테스트를 함께 갱신한다.
"""

from shared.registry import TOOL_REGISTRY

TODAY = "2026-10-03"

# app.py active_plan과 동일한 계약. 바뀌면 양쪽을 함께 갱신한다.
ACTIVE_PLAN = {
    "minh": [
        ("deadline_radar", {}),
        ("remit_optimizer", {}),
        ("form_autofill", {"form_id": "departure_insurance_claim"}),
        ("perception_parse", {}),
    ],
    "suman": [
        ("collateral_calc", {}),
        ("credit_builder", {"months_accrued": 8}),
        ("compliance_reason", {"check_type": "visa_work_eligibility"}),
        ("form_autofill", {"form_id": "alien_registration_renewal"}),
    ],
}


def _run(name: str, args: dict, persona_id: str) -> dict:
    call = dict(args)
    call["persona_id"] = persona_id
    if name == "deadline_radar":
        call["as_of"] = TODAY
    return TOOL_REGISTRY[name](**call)


def test_active_plan_tools_all_registered():
    """능동 plan이 부르는 tool이 전부 레지스트리에 있어야 한다."""
    for persona_id, plan in ACTIVE_PLAN.items():
        for name, _ in plan:
            assert name in TOOL_REGISTRY, f"{persona_id} plan의 {name}이 레지스트리에 없다."


def test_active_plan_fills_cards_for_both_personas():
    """두 페르소나 모두 능동 모드에서 카드가 최소 3개 채워져야 한다.
    카드 None(회색 info 박스)은 데모에서 화면을 비우므로 카메라에 약하다."""
    for persona_id, plan in ACTIVE_PLAN.items():
        cards = 0
        for name, args in plan:
            out = _run(name, args, persona_id)
            if out.get("card") is not None:
                cards += 1
        assert cards >= 3, f"{persona_id} 능동 모드 카드가 {cards}개뿐이다. 3개 이상이어야 데모가 일관된다."


def test_suman_active_plan_has_no_null_cards():
    """수만은 과거에 카드가 비어 화면이 절반 비었다. 이제 plan 4개 모두 카드를 채워야 한다."""
    nulls = []
    for name, args in ACTIVE_PLAN["suman"]:
        out = _run(name, args, "suman")
        if out.get("card") is None:
            nulls.append(name)
    assert not nulls, f"수만 능동 plan에 카드 None인 tool이 있다: {nulls}"
