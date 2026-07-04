"""부문 통합 레지스트리. mcp_servers/ 아래 모든 부문을 자동 발견해 하나로 합친다.

팀원이 규약(CONTRACT.md)에 맞춰 만든 부문 폴더를 mcp_servers/ 아래에 그냥 넣기만 하면
앱 재시작 시 자동으로 tool 실행, tool 스키마, 능동 모드 트리거가 병합된다.
SECTIONS 리스트를 손으로 고칠 필요가 없다. (가드레일 tests/test_contract.py와 같은
pkgutil 자동 발견 방식을 쓴다.)

부문 폴더가 갖춰야 할 것 (CONTRACT.md):
- mcp_servers/<부문>/tools.py 에 TOOL_REGISTRY(dict), ACTIVE_TOOLS(list)
- mcp_servers/<부문>/schemas.py 에 TOOL_SCHEMAS(dict)

병합 결과 3종:
- TOOL_REGISTRY: tool 이름 -> 실행 함수 dict (app.py가 실제 호출)
- TOOL_SCHEMAS: tool 이름 -> Claude tool use 스키마 dict (llm_provider.py가 LLM에 전달)
- ACTIVE_TOOLS: 능동 모드에서 선제 호출하는 tool 이름 리스트 (app.py 능동 점검 루프)

tool 이름은 부문 간 고유해야 한다. 충돌 시 import 시점에 ValueError로 즉시 실패한다.
"""

import importlib
import pkgutil

import mcp_servers


def _discover_sections() -> list:
    """mcp_servers/ 아래 각 부문의 (부문명, tools 모듈, schemas 모듈)을 자동 수집한다.

    tools.py가 없는 폴더는 부문이 아니므로 건너뛴다. schemas.py가 없으면
    그 부문 tool은 실행은 되지만 LLM 대화 모드에는 안 뜨므로 경고 의미로 빈 스키마 처리.
    발견 순서는 폴더 이름 알파벳 순으로 안정화한다(부문 추가해도 기존 순서 유지).
    """
    sections = []
    for mod in sorted(pkgutil.iter_modules(mcp_servers.__path__), key=lambda m: m.name):
        dept = mod.name
        try:
            tools_mod = importlib.import_module(f"mcp_servers.{dept}.tools")
        except ModuleNotFoundError:
            continue  # tools.py 없는 폴더는 부문 아님
        if not hasattr(tools_mod, "TOOL_REGISTRY"):
            continue
        try:
            schemas_mod = importlib.import_module(f"mcp_servers.{dept}.schemas")
        except ModuleNotFoundError:
            schemas_mod = None
        sections.append((dept, tools_mod, schemas_mod))
    return sections


def _merge() -> tuple:
    """발견한 부문을 순회해 세 레지스트리를 병합한다. tool 이름 충돌이면 ValueError."""
    registry: dict = {}
    schemas: dict = {}
    active: list = []
    owner: dict = {}  # tool 이름 -> 소유 부문. 충돌 진단용.

    for dept, tools_mod, schemas_mod in _discover_sections():
        for tool_name in tools_mod.TOOL_REGISTRY:
            if tool_name in owner:
                raise ValueError(
                    f"tool 이름 충돌: '{tool_name}'을 '{owner[tool_name]}'와 "
                    f"'{dept}' 부문이 함께 정의함. CONTRACT 규약대로 이름을 고유하게 바꾸세요."
                )
            owner[tool_name] = dept
        registry.update(tools_mod.TOOL_REGISTRY)
        if schemas_mod is not None and hasattr(schemas_mod, "TOOL_SCHEMAS"):
            schemas.update(schemas_mod.TOOL_SCHEMAS)
        active.extend(getattr(tools_mod, "ACTIVE_TOOLS", []))

    return registry, schemas, active


# 발견된 부문 이름 목록. 사이드바나 디버그에서 "지금 몇 개 부문이 붙었나" 확인용.
SECTIONS = [dept for dept, _, _ in _discover_sections()]

TOOL_REGISTRY, TOOL_SCHEMAS, ACTIVE_TOOLS = _merge()
