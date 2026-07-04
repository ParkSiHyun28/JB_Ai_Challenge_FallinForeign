# shared (공용 모듈)

모든 부문이 함께 쓰는 공용 코드입니다.

| 파일 | 역할 |
|---|---|
| `llm_provider.py` | Claude 전용 호출 엔진. 역할별 2모델(채팅 Haiku / 서류 Sonnet) + 도구 호출 루프 + 스트리밍. 모델은 `.env`의 `CLAUDE_MODEL_CHAT`/`CLAUDE_MODEL_DOCS`로 바꾼다. |
| `personas.py` | 페르소나 2명 고정(minh 베트남 E-9, suman 네팔 D-2). **동결**. 시뮬레이션용 동적 페르소나도 생성. |
| `system_prompt.py` | 공용 시스템 프롬프트 + 언어 자동 감지(ko/vi/ne/en). |
| `registry.py` | `mcp_servers/` 아래 부문을 자동 발견하고 병합. **손댈 일 거의 없음.** |

> 새 부문을 추가해도 `registry.py`가 자동으로 찾아 연결합니다. 이 폴더는 거의 수정하지 않습니다.
