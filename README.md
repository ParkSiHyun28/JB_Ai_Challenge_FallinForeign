# My LifeRoad - 외국인 금융 라이프케어 AI 에이전트

데이콘 JB금융그룹 Fin:AI Challenge 출전작. 외국인의 한국 금융 생활을 입국부터 귀국까지 동행하는 능동형 AI 에이전트다.

> **처음 들어온 팀원은 이 README만 끝까지 읽으면 된다.** 무엇을 만드는지, 어떻게 실행하는지, 내 부문을 어떻게 붙이는지가 다 있다.

---

## 1. 이게 뭐야 (한 장 그림)

외국인 페르소나(베트남 E-9 근로자 / 네팔 D-2 유학생)에게 **묻기 전에 먼저** 금융 손실과 마감을 잡아주는 에이전트다. 챗봇이 아니라 "능동 점검 + 비자별 정밀 자문 + 서류 대리작성"을 한다.

세 부문이 각각 독립 모듈이고, 정적 웹 UI(`web/`)가 FastAPI 백엔드(`backend/`)를 통해 LLM과 부문 tool을 호출한다.

```
web/             정적 챗 UI (HTML/CSS/JS). 브라우저가 직접 띄운다
backend/         FastAPI 서버 (/chat, /personas, /intro). 실제 런타임 진입점
  main.py        엔드포인트
  core.py        streamlit 무관 순수 코어 (마커 분리, tool 디스패치, 인트로 추천)
frontend/
  llm_provider.py  공용 LLM 호출 엔진 + 공급자 스위치 (backend가 직접 import한다)
shared/
  personas.py    페르소나 2명 (전 부문 공용, 동결)
  system_prompt.py  공용 시스템 프롬프트
  registry.py    부문 자동 발견 + 병합 (★ 손댈 일 거의 없음)
mcp_servers/
  asset/         자산 부문 (구현 완료, 팀 표준 예시)
  docs/          서류행정 부문 (구현 완료)
  <내 부문>/      여기에 폴더만 넣으면 자동 연결된다
simulation/      멀티에이전트 시뮬레이션 (독립 정적 HTML)
제출결과물/      데이콘 본선 최종 제출물 (MVP, 명세서, 발표자료, 영상). 자체 README 있음
CONTRACT.md      tool 인터페이스 규약 (부문 만들 때 필독)
AGENT_BRIEF.md   AI에게 부문 작업을 맡길 때 주는 지시문
```

> `frontend/` 폴더엔 LLM 엔진 한 파일만 남아 있다. 이름은 frontend지만 UI가 아니라 backend와 테스트가 함께 쓰는 공용 모듈이다. 실제 화면은 `web/`다.

---

## 2. 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # 키 입력 (아래 3번 참고)
```

서버는 백엔드(FastAPI)와 정적 프론트 둘을 같이 띄운다.

```bash
# 백엔드 (포트 8001)
.venv/bin/uvicorn backend.main:app --port 8001 --reload &
# 정적 프론트 (포트 8000)
.venv/bin/python -m http.server 8000 -d web
```

그다음 브라우저에서 `http://localhost:8000/` 을 연다.

**더 쉬운 방법**: 팀원은 Finder에서 `시연_서버_켜기.command`(맥) 또는 `시연_시작_윈도우.bat`(윈도우)를 더블클릭하면 위 두 서버가 한 번에 뜬다. 자세한 안내는 `팀원_실행안내.md`.

### 테스트
```bash
source .venv/bin/activate
python -m pytest -v
```

---

## 3. LLM 공급자 (무료/유료 스위치)

`.env`의 `LLM_PROVIDER` 한 줄로 바꾼다. 코드는 그대로다.

| 공급자 | 설정값 | 키 | 비용 | 특징 |
|---|---|---|---|---|
| **Gemini** | `gemini` | `GEMINI_API_KEY` (AIza…) | 무료 | 한국어 안정 + tool 정확. tool 질문 약 3~4초. **현재 기본값** |
| Groq | `groq` | `GROQ_API_KEY` (gsk_…) | 무료 | Llama 3.3 70B는 긴 한국어 프롬프트에서 tool 형식 오류가 잦아 재시도로 느려진다. 비권장 |
| Ollama | `ollama` | 불필요 | 무료 로컬 | 인터넷 없이 구동. 4b 모델은 한 턴 20초대로 느리고 한국어 가끔 깨짐 |
| Claude | `claude` | `ANTHROPIC_API_KEY` | 유료 | 본선용. 최고 품질. 진짜 토큰 스트리밍 |

> Gemini 무료 티어는 모델별 일일 한도가 있다. `gemini-2.5-flash`는 한도가 빡빡하니 시연 전 새 프로젝트 키를 발급해 두면 안정적이다. 발급은 https://aistudio.google.com/apikey 에서 카드 없이 된다.

- 기본 공급자는 `gemini`다. 로컬에서 ollama로 바꾸려면 `.env`에 `LLM_PROVIDER=ollama`를 추가한다.
- 무료 키 발급: Gemini는 https://aistudio.google.com/apikey / Groq는 https://console.groq.com (둘 다 카드 불필요).
- `.env`는 깃에 안 올라간다(`.gitignore`). 각자 자기 키를 `.env`에 넣는다. 견본은 `.env.example`.

> **보안 권고** - 로컬 `.env`의 키가 외부에 노출된 적이 있으면(공유 또는 스크린샷 등) Google AI Studio와 Groq 콘솔에서 키를 재발급(rotate)하라. `.env`는 절대 커밋하지 않는다.

---

## 4. 내 부문을 붙이는 법 (★ 자동 연결)

**핵심: `mcp_servers/` 아래에 규약대로 만든 폴더를 넣기만 하면 서버 재시작 시 자동으로 연결된다.** `registry.py`나 `backend/`를 손댈 필요 없다.

### 절차
1. 이 repo를 clone 한다. (GitHub: `ParkSiHyun28/liferoad_ai_agent`)
2. **CONTRACT.md를 읽는다.** (입출력 규약. 이걸 어기면 통합이 깨진다)
3. `mcp_servers/asset` 폴더를 자기 부문 영문명으로 복제한다. (예: `mcp_servers/fraud/`)
   - 폴더명은 **반드시 영문**. 한글이면 import가 깨진다.
4. `tools.py`의 함수를 자기 부문 tool로 바꾼다. 입출력 4키 규약(`summary/detail/numbers/card`)은 그대로 지킨다.
5. `schemas.py`의 `TOOL_SCHEMAS`도 자기 tool에 맞게 바꾼다.
6. `python -m pytest`로 검증한다. **가드레일(tests/test_contract.py)이 새 부문도 자동 검사**한다. 통과하면 규약 OK.
7. push 하거나, 폴더를 압축해 보내면 받는 쪽이 `mcp_servers/`에 풀어 넣는다. 끝.

### 폴더만 넣으면 왜 자동으로 붙나
`shared/registry.py`가 앱 시작 때 `mcp_servers/` 아래를 스캔해서 `TOOL_REGISTRY`가 있는 폴더를 전부 찾아 병합한다. tool 실행, LLM 스키마, 능동 모드 트리거가 한꺼번에 합쳐진다. tool 이름이 다른 부문과 겹치면 즉시 에러로 알려준다.

### AI(LLM)에게 부문 작업을 맡길 경우
자기 LLM에게 이렇게 시키면 된다:
> **"이 repo를 읽고 AGENT_BRIEF.md 지시를 따라줘: https://github.com/ParkSiHyun28/liferoad_ai_agent"**

`AGENT_BRIEF.md`가 AI에게 주는 작업 지시문이다.

---

## 5. 현재 부문 상태

- **asset (자산)** - 구현 완료. 팀 표준 예시. tool 5개: deadline_radar, pension_estimator, collateral_calc, remit_optimizer, credit_builder.
- **docs (서류행정)** - 구현 완료. tool 3개: perception_parse(OCR 파싱), compliance_reason(전세사기/비자 가드레일), form_autofill(신청서 자동작성).
- **fraud (사기탐지)** - 미합류. 폴더 오면 `mcp_servers/fraud/`에 넣으면 자동 연결된다.

페르소나 2명(동결): `minh` 응웬 반 민(베트남 E-9 근로자), `suman` 수만 라이(네팔 D-2 유학생).

---

## 6. 온라인 배포 (백엔드 Render + 정적 프론트)

구조상 둘을 따로 올린다. 백엔드는 FastAPI 서버, 프론트는 정적 파일이다.

### 배포 전 확인
- `.env.example`을 열어 필요한 키 목록을 파악한다.
- `.env`가 커밋에 포함되지 않았는지 `git status`로 확인한다(`.gitignore`로 막혀 있다).

### 백엔드 (Render)
1. **GitHub에 push**
   ```bash
   git push origin main
   ```
2. https://render.com 에서 New Web Service → `ParkSiHyun28/liferoad_ai_agent` 선택.
3. Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Environment에 키 입력: `LLM_PROVIDER`, `GEMINI_API_KEY`(또는 본선용 `ANTHROPIC_API_KEY`).
5. 배포되면 `https://<서비스명>.onrender.com` 형태의 API URL이 생긴다.

### 정적 프론트
- `web/config.js`의 `PROD_API`를 위에서 받은 Render API URL로 맞춘다.
- `web/` 폴더를 정적 호스팅(Cloudflare Pages 등)에 올린다. 빌드 과정 없이 그대로 서빙한다.

### 본선(Claude) 전환
- Render Environment에서 `LLM_PROVIDER = claude`로 바꾸고 `ANTHROPIC_API_KEY = sk-ant-...`를 추가한다.
- 저장 후 재배포하면 반영된다.
