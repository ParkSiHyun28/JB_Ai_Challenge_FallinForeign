"""사기탐지 tool 의 Claude tool use 용 JSON 스키마. server.py 와 app.py 가 공유한다.
Anthropic SDK tool 형식(name, description, input_schema)을 따른다.
자산 부문 schemas.py 를 본떠 만든다."""

_PERSONA_PROP = {
    "persona_id": {
        "type": "string",
        # enum 을 두지 않는다. 동적 페르소나 50 에서 100 명을 enum 에 싣지 않으려는 의도다.
        # 올바른 id 는 시스템 프롬프트의 현재 사용자 블록과 user 메시지의 '[페르소나: <id>]'
        # 태그가 강하게 유도한다. 잘못된 id 는 get_persona 가 ValueError 를 던지고
        # llm_provider 가 그 예외를 잡아 안전한 오류 dict 로 바꾸므로 앱이 죽지 않는다.
        "description": (
            "페르소나 식별자. 시스템 프롬프트의 현재 사용자 블록과 사용자 메시지의 "
            "'[페르소나: <id>]' 태그에 적힌 id 를 그대로 사용한다. 예 minh suman e9_vn_001."
        ),
    }
}

TOOL_SCHEMAS = {
    "register_baseline": {
        "name": "register_baseline",
        "description": (
            "국적 그룹별 정상 거래 분포를 학습해 기준선을 세운다. 분위수 임계로 오탐률만 "
            "통제하며 사기 적발률과 섞지 않는다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
    "score_transaction": {
        "name": "score_transaction",
        "description": (
            "한 거래의 위험 점수를 0 에서 100 으로 매긴다. 발동한 위험 신호의 가중치 합으로 "
            "점수를 내고 주의 또는 즉시 보류 판정을 붙인다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_PERSONA_PROP,
                "tx_id": {
                    "type": "string",
                    "description": "채점할 거래 식별자. 생략하면 가장 위험한 거래를 채점한다.",
                },
            },
            "required": ["persona_id"],
        },
    },
    "detect_account_takeover": {
        "name": "detect_account_takeover",
        "description": (
            "계좌양도와 명의도용 패턴을 탐지한다. 미등록 새 기기 접속과 잔액 전액 인출이 "
            "함께 나오고 출국 임박이나 과다 금액이 겹치면 계좌양도로 판정한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
    "request_verification": {
        "name": "request_verification",
        "description": (
            "보류된 의심 거래에 대해 고객 모국어로 본인확인 푸시를 보낸다. 한국어 안내로는 "
            "강요와 기망 여부 확인이 어려운 외국인 특화 문제를 다룬다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {**_PERSONA_PROP},
            "required": ["persona_id"],
        },
    },
}
