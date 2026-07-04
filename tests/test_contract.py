"""공용 규약 가드레일. 팀원이 공용 파일이나 tool 출력 형식을 어기면 이 테스트가 실패한다.
push 전 `python -m pytest`를 돌리면 위반이 빨간색으로 드러난다. 어기지 말 것.

부문 작업자에게: 이 파일을 통과 못 하면 통합이 깨진다. 테스트를 고쳐서 통과시키지 말고,
코드를 규약에 맞게 고쳐서 통과시켜라. 이 파일 자체를 수정하는 것은 금지다."""

import importlib
import pkgutil

import mcp_servers
from shared.personas import PERSONAS


# ---------------------------------------------------------------------------
# 1. 페르소나 공용 데이터 동결. 임의 수정 금지.
#    새 필드가 필요하면 자산 담당자와 협의 후 이 테스트도 함께 갱신한다.
# ---------------------------------------------------------------------------

def test_personas_are_exactly_two():
    assert set(PERSONAS.keys()) == {"minh", "suman"}, "페르소나는 minh와 suman 둘로 고정. 추가나 삭제 금지."


def test_persona_core_fields_frozen():
    # 부문 작업 중 바뀌면 안 되는 핵심 값. 통합 시연 시나리오의 기준이다.
    assert PERSONAS["minh"]["visa"] == "E-9"
    assert PERSONAS["minh"]["country"] == "베트남"
    assert PERSONAS["minh"]["social_security_treaty"] is False
    assert PERSONAS["suman"]["visa"] == "D-2"
    assert PERSONAS["suman"]["country"] == "네팔"
    assert PERSONAS["suman"]["deposit_balance_krw"] == 20_000_000


# ---------------------------------------------------------------------------
# 2. 모든 부문의 모든 tool은 출력 dict 4키 규약을 지켜야 한다.
#    mcp_servers 아래 모든 부문 패키지를 자동 발견해 검사한다.
#    부문을 새로 추가하면 이 테스트가 자동으로 그 부문도 검사한다.
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"summary", "detail", "numbers", "card"}
CARD_KEYS = {"icon", "head", "body", "metric"}


def _discover_department_tools():
    """mcp_servers 아래 각 부문의 (부문명, TOOL_REGISTRY)를 모은다."""
    found = []
    for mod in pkgutil.iter_modules(mcp_servers.__path__):
        dept = mod.name
        try:
            tools = importlib.import_module(f"mcp_servers.{dept}.tools")
        except ModuleNotFoundError:
            continue
        registry = getattr(tools, "TOOL_REGISTRY", None)
        if registry:
            found.append((dept, registry))
    return found


def test_at_least_asset_department_present():
    depts = dict(_discover_department_tools())
    assert "asset" in depts, "자산 부문이 표준 예시로 존재해야 한다."


def test_every_tool_output_follows_contract():
    """모든 부문 모든 tool을 두 페르소나로 호출해 출력 규약을 검증한다.
    tool 출력은 반드시 summary, detail, numbers, card 4키를 가진다.
    card는 None이거나 icon, head, body, metric 4키 dict다."""
    for dept, registry in _discover_department_tools():
        for tool_name, func in registry.items():
            for pid in ("minh", "suman"):
                kwargs = {"persona_id": pid}
                # as_of가 필요한 tool(deadline_radar 등)에 기준일을 채운다.
                if "as_of" in getattr(func, "__code__").co_varnames:
                    kwargs["as_of"] = "2026-10-03"
                result = func(**kwargs)
                label = f"{dept}.{tool_name}({pid})"
                assert isinstance(result, dict), f"{label}: dict를 반환해야 한다."
                assert set(result.keys()) >= REQUIRED_KEYS, (
                    f"{label}: 출력에 {REQUIRED_KEYS} 4키가 모두 있어야 한다. "
                    f"현재 키: {set(result.keys())}"
                )
                assert isinstance(result["numbers"], dict), f"{label}: numbers는 dict."
                card = result["card"]
                assert card is None or set(card.keys()) == CARD_KEYS, (
                    f"{label}: card는 None이거나 {CARD_KEYS} 4키 dict여야 한다."
                )
