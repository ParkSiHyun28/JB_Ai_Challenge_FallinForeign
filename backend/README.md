# backend (FastAPI 서버)

실제 런타임 진입점입니다. 브라우저(`web/`)의 요청을 받아 LLM과 부문 도구를 호출합니다.

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 엔드포인트. `/chat`(대화 스트리밍), `/personas`, `/intro`. |
| `core.py` | 순수 코어 로직. 마커 분리(`<<NEXT>>`, `<<DONE>>`), 도구 디스패치, 인트로 추천. |
| `schemas.py` | 요청/응답 Pydantic 모델. |
| `tests/` | 백엔드 단위 테스트(API, 코어). |

실행: `uvicorn backend.main:app --port 8001 --reload`
