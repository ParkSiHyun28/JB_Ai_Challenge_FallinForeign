# My LifeRoad 디버깅, 보강, 온라인 배포 설계서

작성일 2026-06-05. 대상 repo `liferoad_ai_agent` (GitHub `ParkSiHyun28/liferoad_ai_agent`).

## 목표

데이콘 JB Fin:AI Challenge 제출작 My LifeRoad를 (1) 전수 디버깅하고 (2) 자산, 서류 부문을 검토, 보강하고 (3) Streamlit Community Cloud에 공개 URL로 배포한다. 사기탐지(fraud) 부문은 팀원 몫이라 제외한다.

## 결정 사항 (사용자 확정)

| 항목 | 결정 |
|---|---|
| fraud 부문 | 비워둠. 폴더 넣으면 자동연결되는 현 구조 유지 |
| 배포 | Streamlit Community Cloud. 공개 URL |
| 시연 LLM | Gemini 무료. README에 Claude 본선 전환 한 줄 |
| 시연 흐름 | 능동 점검 → 자유대화. 추천 질문 3-4개를 README와 사이드바에 고정 |

## 근거: 다차원 감사 결과

5개 차원(correctness, llm-integration, deploy, demo, numbers)을 병렬 감사하고 각 발견을 적대 검증했다. 26개 확정, 7개 기각. 확정 발견을 4개 묶음으로 정리한다.

### 묶음 A — 배포 블로커 (이걸 안 고치면 온라인 데모 불가)

- **A1 secrets 브리지 부재**: 코드가 `os.environ`만 읽는다. Streamlit Cloud는 `st.secrets`에 키를 넣는다. 브리지 없으면 클라우드에서 Gemini 키를 못 찾아 채팅이 죽는다.
- **A2 기본 공급자=ollama**: `LLM_PROVIDER` 기본값이 `ollama`. 클라우드엔 로컬 ollama가 없어 `localhost:11434` 연결 실패.
- **A3 secrets 템플릿, 배포 문서 부재**: 배포자가 어떤 secrets를 넣어야 할지 모른다.
- **A4 ollama 클라우드 오류 메시지 불친절**: 클라우드에서 ollama 선택 시 원인 불명 오류.
- **A5 .env 실제 키 보유**: gitignore돼 있고 push 이력 없음(위험 미실현). 그래도 키 회전 권고를 문서화한다.

### 묶음 B — LLM 견고성 (데모 중 크래시 위험)

- **B1 무한 루프 방지 부재**: `_run_claude`, `_run_openai_compat` 둘 다 `while True`에 반복 상한 없음. 병적 tool 호출 시 무한 루프.
- **B2 tool 인자 JSON 파싱 무방비**: `json.loads(tc.function.arguments)`에 try-except 없음. 모델이 깨진 JSON 뱉으면 크래시.
- **B3 잘못된 tool 이름 = raw KeyError**: `TOOL_REGISTRY[name]`가 KeyError 발생. 능동 모드는 try/except조차 없어 앱 전체가 죽음.
- **B4 실패한 tool이 처리과정에 안 뜸**: `traced_run_tool`에서 tool이 예외 던지면 `on_step` 호출 전에 빠져나가 시각화에 안 보임.
- **B5 groq 재시도 문자열 매칭 취약** (중간): `tool_use_failed` 부분문자열 의존.
- **B6 as_of 덮어쓰기 deadline_radar 한정** (낮음): 미래 날짜 tool 추가 시 깨짐.
- **B7 strip_emoji ZWJ 누락** (낮음): 가족 이모지 등 ZWJ 시퀀스 잔여물.

### 묶음 C — 데모 품질 (수만 페르소나가 카메라에서 빈약)

- **C1 수만 능동 모드 절반 공백**: 수만(D-2)은 `deadline_radar`, `remit_optimizer` 카드가 None. 회색 info 박스 2개로 떠서 "묻기 전에 먼저 알림" 가치가 안 보임. 민(E-9)은 카드 가득, 수만은 빈약 → 일관성 깨짐.
- **C2 수만 핵심 가치 능동 모드에서 누락**: `collateral_calc`(2천만 예치금 → 1900만 담보대출)와 `credit_builder`(Thin Filer 대안신용)가 ACTIVE_TOOLS에 없음. 수만에게 가장 중요한 두 tool이 능동 모드에서 안 나옴.
- **C3 form_autofill 항상 일반 양식**: 두 페르소나 모두 외국인등록증 갱신서만 나옴. 민에겐 반환일시금, 출국만기보험 청구서가 더 임팩트 있는데 안 띄움.
- **C4 deadline_radar 수만 카드 None** (중간): C1의 일부.
- **C5 perception_parse 항상 성공** (낮음): 실명 불일치 6% 분기가 죽어 있어 항상 성공만 보임.

### 묶음 D — 수치 무결성 (심사위원 검증 대상)

- **D1 22.4% 문자열 취약**: `int(rate*100)` + 하드코딩 `.4%`. 지금은 맞지만 상수 바뀌면 깨짐. CONTRACT의 "결과 문자열 하드코딩 금지" 위반.
- **D2 소멸시효 3년 4곳 하드코딩**: data.py에 상수 없음. 심사위원이 출처를 못 찾음.
- **D3 죽은 상수**: `FX_*` 3개, `STUDENT_JOB_HOPE_RATE`, `PENSION_TOTAL_PAYOUT_2023_KRW`, `UNCLAIMED_INSURANCE_KRW`(tool에서 한국어 문자열로 재타이핑됨).

## 설계: 어떻게 고치나

### 1. 공급자 설정 모듈 분리 (A1, A2, A4)

새 파일 `shared/secrets_bridge.py`. `st.secrets`를 먼저 보고 없으면 `os.environ`을 보는 단일 `get_secret(key, default)` 함수. app.py가 `llm_provider` import **전에** 이 브리지로 secrets를 `os.environ`에 주입한다. 이러면 기존 `os.environ.get` 코드를 다 안 고쳐도 된다(최소 개입). 단 import 순서가 핵심이라 app.py 최상단에서 브리지를 먼저 실행한다.

`llm_provider.py`의 기본 공급자를 `gemini`로 바꾼다. 로컬은 `.env`로 `LLM_PROVIDER=ollama` 덮어쓰면 됨. ollama를 클라우드에서 고르면 연결 오류에 안내 메시지를 붙인다.

### 2. tool 호출 안전망 (B1, B2, B3, B4)

`llm_provider.py`:
- 두 루프에 `MAX_TOOL_ITERATIONS = 8` 상한. 초과 시 명확한 메시지로 종료.
- `json.loads` try-except. 깨진 인자는 빈 dict로 폴백하고 처리과정에 기록.
- `traced_run_tool`이 tool 예외를 잡아 `on_step("tool_error", ...)` 보고 후 안전 dict 반환(앱 안 죽임).

`app.py`:
- `run_tool`에 tool 이름 검증. 능동 모드 루프에 try/except.
- `render_step`이 tool_error 종류도 그릴 수 있게 확장.

### 3. 능동 모드 페르소나 인지 (C1, C2, C3, C4)

핵심 보강. `app.py` 능동 모드를 페르소나별 tool 묶음으로 바꾼다. CONTRACT의 ACTIVE_TOOLS는 부문 기본값으로 두되, app.py가 페르소나에 맞는 tool과 인자를 선택하는 `active_plan(persona_id)` 함수를 둔다.

- 민(E-9): `deadline_radar`, `remit_optimizer`, `form_autofill(departure_insurance_claim)`, `perception_parse`.
- 수만(D-2): `collateral_calc`, `credit_builder(months_accrued=8)`, `compliance_reason(visa_work_eligibility)`, `form_autofill(alien_registration_renewal)`.

이러면 두 페르소나 모두 능동 모드에서 카드 3-4개가 채워진다. shared/personas.py, system_prompt.py, asset 폴더는 안 건드린다(동결 규칙 준수). docs tools.py는 보강 대상이라 허용.

### 4. 수치 상수화 (D1, D2, D3)

- D1: `f"{rate*100:.1f}%"`로 교체(asset/tools.py 두 곳). asset 폴더는 동결이지만 이건 보강 요청 범위. **확인 필요** — 아래 미해결 참조.
- D2: `data.py`에 `CLAIM_DEADLINE_YEARS = 3` 추가하고 4곳을 참조로 교체.
- D3: 죽은 상수 두 갈래. (a) tool에서 한국어로 재타이핑된 억-수치(3,294억, 307.6억, 30%)는 기존 상수에서 계산식으로 도출. (b) 진짜 미사용 상수(`FX_*`, `STUDENT_JOB_HOPE_RATE`)는 제거하거나 tool에서 활용. 활용 쪽이 데모 풍부함에 유리.

### 5. 배포 자산 (A3, A5)

- `.streamlit/secrets.example.toml` 생성(플레이스홀더). gitignore는 `secrets.toml`만 막고 example은 올린다.
- `requirements.txt`에 버전 안전화. python 버전은 Streamlit Cloud 기본(3.11~3.13)에 맞춰 `runtime.txt` 또는 미지정(클라우드 기본). 로컬 .venv가 3.14인 점과 분리.
- README에 "온라인 배포" 절 추가: GitHub push → Streamlit Cloud 연결 → Secrets 탭에 `LLM_PROVIDER`, `GEMINI_API_KEY` 입력 → 공개 URL. 키 회전 권고도 명시.
- 시연 시나리오 절: 페르소나별 추천 질문 3-4개.

### 6. 테스트

- 새 회귀 테스트: 능동 모드 plan이 두 페르소나 모두 카드를 채우는지, 상수화가 올바른지, secrets 브리지 폴백 동작.
- 기존 `tests/test_contract.py`는 동결. 통과 유지.
- 전체 `pytest` 그린 유지.

## 범위 밖 (안 함)

- fraud 부문 구현 (팀원 몫).
- `shared/personas.py`, `shared/system_prompt.py`, `mcp_servers/asset/server.py` 구조 변경.
- `tests/test_contract.py` 수정.
- 새 LLM 공급자 추가.

## 미해결 (구현 전 확인 필요)

1. **asset/tools.py 보강 허용 범위**: AGENT_BRIEF는 "asset 폴더 수정 금지"라고 못박았다. 그러나 사용자는 "자산관리 에이전트 검토 및 보강 수정"을 명시 지시했다. asset의 D1(22.4% 취약), D2(소멸시효 상수화), C2(ACTIVE_TOOLS)는 asset 파일 안에 있다. 사용자 지시가 AGENT_BRIEF보다 우선이므로 보강한다. 단 페르소나 핵심 값과 출력 4키 규약은 유지해 test_contract 통과를 보장한다.
2. **능동 모드 페르소나 plan 위치**: CONTRACT의 부문별 ACTIVE_TOOLS를 살리되 app.py가 페르소나 인지 선택을 얹는 방식으로 한다. 부문 자동연결 원칙을 깨지 않는다(fraud 폴더가 와도 그 ACTIVE_TOOLS는 그대로 병합됨).

## 구현 순서

1. 배포 안전망 (secrets 브리지, 기본 공급자) — 온라인 가능의 전제.
2. LLM 견고성 (루프 상한, 예외 안전망).
3. 능동 모드 페르소나 인지 보강.
4. 수치 상수화, 죽은 코드 정리.
5. 배포 자산, README, 시나리오.
6. 테스트 추가, 전체 pytest 그린, 로컬 Gemini 실구동 검증.
7. 커밋, push, Streamlit Cloud 배포, 공개 URL 확인, 시연 가이드.
