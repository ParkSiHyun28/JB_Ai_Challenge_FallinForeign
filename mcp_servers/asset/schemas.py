"""자산 tool의 Claude tool use용 JSON 스키마. server.py와 app.py가 공유한다.
Anthropic SDK tool 형식(name, description, input_schema)을 따른다."""

_PERSONA_PROP = {
    "persona_id": {
        "type": "string",
        # enum을 두지 않는다. 동적 페르소나 50~100명을 enum에 싣지 않으려는 의도다.
        # 올바른 id는 시스템 프롬프트의 현재 사용자 블록과 user 메시지의 '[페르소나: <id>]'
        # 태그가 강하게 유도한다. 잘못된 id는 get_persona가 ValueError를 던지고
        # llm_provider가 그 예외를 잡아 안전한 오류 dict로 바꾸므로 앱이 죽지 않는다.
        "description": (
            "페르소나 식별자. 시스템 프롬프트의 현재 사용자 블록과 사용자 메시지의 "
            "'[페르소나: <id>]' 태그에 적힌 id를 그대로 사용한다. 예 minh suman e9_vn_001."
        ),
    }
}

TOOL_SCHEMAS = {
    "deadline_radar": {
        "name": "deadline_radar",
        "description": "반환일시금과 출국만기보험의 청구 마감 D-Day를 추적한다. 출국 예정일 기준 남은 일수와 소멸 위험을 계산한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_PERSONA_PROP,
                "as_of": {
                    "type": "string",
                    "description": "기준일 'YYYY-MM-DD'. 생략 시 호출부에서 오늘 날짜를 채운다.",
                },
            },
            "required": ["persona_id", "as_of"],
        },
    },
    "pension_estimator": {
        "name": "pension_estimator",
        "description": (
            "국민연금 반환일시금 수령 가능 여부를 국적과 비자 기준으로 판정하고 "
            "예상 수령액(납부보험료+이자)을 공단 공식으로 계산한다. "
            "매달 공제돼 온 보험료를 귀국 시 돌려받는 금액이다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
    "collateral_calc": {
        "name": "collateral_calc",
        "description": "잔고증명 예치금 기준 예금담보대출 한도(최대 95%)를 산출한다. 비자 잔고 요건 위반 없는 인출 범위를 안내한다.",
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
    "remit_optimizer": {
        "name": "remit_optimizer",
        "description": (
            "송금 경로별 진짜 총비용(고정수수료+환율마진)을 비교해 최저 경로와 "
            "귀국 전까지의 총 절감액을 계산한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
    "credit_builder": {
        "name": "credit_builder",
        "description": (
            "통신비와 공과금과 월세 납부 이력의 대안신용 축적 단계를 계산한다. "
            "축적 개월은 페르소나 데이터에서 자동 도출하며 다음 가점 단계 도달 시점을 예고한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
}
