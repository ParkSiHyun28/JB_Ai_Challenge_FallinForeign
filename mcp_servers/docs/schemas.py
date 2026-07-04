"""서류행정 tool의 Claude tool use용 JSON 스키마. server.py와 backend가 공유한다.
Anthropic SDK tool 형식(name, description, input_schema)을 따른다."""

_PERSONA_PROP = {
    "persona_id": {
        "type": "string",
        # enum을 두지 않는다. 동적 페르소나 50~100명을 enum에 싣지 않으려는 의도다(asset과 동일).
        # 올바른 id는 시스템 프롬프트의 현재 사용자 블록과 user 메시지의 '[페르소나: <id>]' 태그가 유도한다.
        "description": (
            "페르소나 식별자. 시스템 프롬프트의 현재 사용자 블록과 사용자 메시지의 "
            "'[페르소나: <id>]' 태그에 적힌 id를 그대로 사용한다. 예 minh suman e9_vn_001."
        ),
    }
}

TOOL_SCHEMAS = {
    "form_autofill": {
        "name": "form_autofill",
        "description": (
            "정부 PDF 신청서를 회원 프로필 정보로 자동작성한다. 스캔 없이 등록된 회원 정보로 "
            "채울 수 있는 칸만 채운다. 실제 PDF 템플릿을 갖춘 5종을 지원한다: "
            "외국인등록증 갱신 신청서, 국민연금 반환일시금 신청서, 출국기한유예신청서, "
            "거주 및 숙소제공 확인서, 외국인 유학생 시간제취업 확인서."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_PERSONA_PROP,
                "form_id": {
                    "type": "string",
                    "enum": [
                        "alien_registration_renewal",
                        "pension_return_claim",
                        "departure_postpone",
                        "residence_confirmation",
                        "parttime_work_confirmation",
                    ],
                    "description": "자동작성할 신청서 양식 ID(작성 가능 5종). 기본값 alien_registration_renewal.",
                },
            },
            "required": ["persona_id"],
        },
    },
}
