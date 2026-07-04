# tool 인터페이스 규약 (CONTRACT)

My LifeRoad 통합 AI 에이전트의 모든 부문은 이 규약을 따른다. 자산 부문(mcp_servers/asset)이 표준 예시다. 사기와 서류 부문은 그 폴더를 복제해 만든다.

## 폴더 구조 (부문마다 동일)
```
mcp_servers/<부문>/
├─ __init__.py
├─ data.py        # mock 상수와 계산 보조
├─ tools.py       # tool 순수 함수 + TOOL_REGISTRY + ACTIVE_TOOLS
├─ schemas.py     # TOOL_SCHEMAS
├─ server.py      # MCP stdio 서버 (asset/server.py를 부문명만 바꿔 복제)
└─ tests/
   └─ test_tools.py
```

## tool 함수 규약
- 순수 함수다. MCP와 Claude를 import 하지 않는다.
- 입력은 키워드 인자. 첫 인자는 항상 `persona_id`("minh" 또는 "suman").
- 출력은 dict. 필수 키 4개: `summary`(str), `detail`(str), `numbers`(dict), `card`(dict 또는 None).
- card 구조: `{"icon": str, "head": str, "body": str, "metric": str}`. 형식은 발표 시뮬레이터와 동일하다.
- 모든 수치는 data.py 상수에서 계산식으로 도출한다. 결과 문자열 하드코딩 금지.
- tool 이름은 동사_명사 snake_case. 예: score_transaction, detect_account_takeover.

## TOOL_REGISTRY
tools.py 맨 끝에 둔다.
```python
TOOL_REGISTRY = {"tool이름": 함수, ...}
ACTIVE_TOOLS = ["능동모드에서_먼저_부를_tool", ...]
```

## TOOL_SCHEMAS (schemas.py)
각 tool마다 Anthropic SDK 형식.
```python
TOOL_SCHEMAS = {
  "tool이름": {
    "name": "tool이름",
    "description": "한국어 한 줄 설명",
    "input_schema": {"type": "object", "properties": {...}, "required": [...]},
  },
}
```
persona_id 프로퍼티는 enum ["minh", "suman"]로 고정한다.

## 공용 자원
- 페르소나: `from shared.personas import get_persona, PERSONAS`. 새 페르소나 필드가 필요하면 PR로 협의 후 추가한다. 임의 수정 금지.
- 시스템 프롬프트: `from shared.system_prompt import build_system_prompt`. 부문별로 바꾸지 않는다.

## 통합
`shared/registry.py`가 `mcp_servers/` 아래 모든 부문을 자동 발견해 병합한다. 규약을 지킨 폴더를 `mcp_servers/<영문부문명>/`에 넣으면 앱 재시작 시 자동 연결된다. `frontend/app.py`나 `shared/registry.py`에 import를 손으로 추가할 필요가 없다. tool 이름이 다른 부문과 겹치면 즉시 에러가 난다.

## 가드레일 (규약 위반 자동 차단)
repo 루트 `tests/test_contract.py`가 이 규약을 기계적으로 검사한다. 페르소나 핵심 값 동결과 모든 부문 tool의 출력 4키 형식을 자동으로 확인한다. 부문을 새로 추가하면 그 부문 tool도 자동 검사 대상이 된다. `python -m pytest`로 돌려 통과하는지 확인한다. 이 파일은 수정하지 않는다. 위반 시 테스트가 아니라 코드를 고친다.
