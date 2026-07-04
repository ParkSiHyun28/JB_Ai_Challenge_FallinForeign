# frontend (LLM 호출 엔진)

> 이름은 frontend지만 화면이 아닙니다. 실제 화면은 `web/`입니다.
> 여기는 backend와 테스트가 함께 쓰는 **공용 LLM 엔진**입니다.

| 파일 | 역할 |
|---|---|
| `llm_provider.py` | LLM 공급자 스위치(gemini/claude/groq/ollama) + 도구 호출 루프 + SSE 스트리밍. |

공급자는 `.env`의 `LLM_PROVIDER` 한 줄로 바꿉니다. 기본값은 gemini(무료), 본선은 claude.
