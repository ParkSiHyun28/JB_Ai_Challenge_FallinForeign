# My LifeRoad - 외국인 금융 라이프케어 AI 에이전트

**데이콘 JB금융그룹 Fin:AI Challenge 본선 진출작 (팀 Fall in Foreign)**

외국인의 한국 금융 생활을 입국부터 귀국까지 동행하는 능동형 AI 에이전트입니다. 단순 챗봇이 아니라 고객이 묻기 전에 먼저 금융 손실과 마감을 짚어 주고, 비자별 정밀 자문과 정부 서류 대리작성, 실시간 이상거래 탐지까지 수행합니다.

대상 페르소나는 두 명으로 고정되어 있습니다. 베트남 E-9 근로자(응웬 반 민)와 네팔 D-2 유학생(수만 라이)입니다.

---

## 1. 시스템 개요

세 부문(자산, 서류행정, 사기탐지)이 각각 독립 모듈로 구성되며, 정적 웹 UI(`web/`)가 FastAPI 백엔드(`backend/`)를 통해 Claude 및 각 부문의 tool을 호출합니다. 새 부문은 `mcp_servers/` 아래에 규약에 맞는 폴더를 넣는 것만으로 서버 재시작 시 자동 연결됩니다.

```
web/               정적 챗 UI (HTML/CSS/JS). 고객 관점 화면
fraud_console/     기업 관점 이상거래 관제 콘솔 (정적 HTML, 분석가용)
backend/
  main.py          FastAPI 엔드포인트 (/chat, /personas, /intro, /fraud/*)
  core.py          순수 코어 (마커 분리, tool 디스패치, 능동 점검 계획)
  fraud_api.py     사기탐지 관제 API (대기열, 케이스 처리, 결정)
shared/
  llm_provider.py  공용 Claude 호출 엔진 (채팅 Haiku, 서류 Sonnet 2모델)
  personas.py      페르소나 2명 (전 부문 공용, 동결)
  system_prompt.py 공용 시스템 프롬프트
  registry.py      부문 자동 발견 및 병합
mcp_servers/
  asset/           자산 부문 (구현 완료)
  docs/            서류행정 부문 (구현 완료)
  fraud_guard/     사기탐지 부문 (구현 완료. 실제 ML 엔진 탑재)
simulation/        멀티에이전트 시뮬레이션 (독립 정적 HTML)
제출결과물/         데이콘 본선 최종 제출물 (MVP, 명세서, 발표자료, 영상)
CONTRACT.md        tool 인터페이스 규약
AGENT_BRIEF.md     부문 작업 지시문
```

시연은 서버 세 개를 함께 사용합니다. 백엔드(8001), 고객 관점 웹(8000), 기업 관점 관제 콘솔(8002)입니다.

---

## 2. 실행 방법

### 원클릭 실행 (권장)

Finder에서 아래 파일을 더블클릭하면 서버 세 개가 한 번에 뜨고 브라우저가 자동으로 열립니다.

- macOS: `시연_시작_맥.command` (파이썬과 가상환경이 없으면 설치까지 자동 수행)
- Windows: `시연_시작_윈도우.bat`

자세한 안내는 `팀원_실행안내.md`를 참고하십시오.

### 수동 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # ANTHROPIC_API_KEY 입력 (3장 참고)
```

```bash
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8001 &   # 백엔드
.venv/bin/python -m http.server 8000 -d web &                        # 고객 관점
.venv/bin/python -m http.server 8002 -d fraud_console &              # 기업 관점 관제 콘솔
```

브라우저에서 `http://localhost:8000/` 을 엽니다. 화면 우측 상단에서 고객 관점과 기업 관점을 전환할 수 있습니다.

### 테스트

```bash
source .venv/bin/activate
python -m pytest -v
```

---

## 3. 사용 모델

Claude API만 사용하며, 역할에 따라 모델을 분리합니다. `.env`에서 조정할 수 있습니다.

| 역할 | 환경변수 | 기본 모델 | 선정 이유 |
|---|---|---|---|
| 채팅 응답 | `CLAUDE_MODEL_CHAT` | `claude-haiku-4-5` | 대화는 응답 속도 우선 |
| 서류 작성 턴 | `CLAUDE_MODEL_DOCS` | `claude-sonnet-4-6` | 신청서 판단은 정확성 우선 |

- 서류 관련 발화는 `backend/core.py`의 `pick_model`이 자동으로 Sonnet으로 라우팅합니다.
- 필요한 키는 `ANTHROPIC_API_KEY` 하나입니다. 발급: https://console.anthropic.com
- `.env`는 저장소에 포함되지 않습니다(`.gitignore`). 각자 자신의 키를 `.env`에 입력하며, 견본은 `.env.example`입니다.
- 사기탐지 관제 콘솔과 이상탐지 엔진은 API 키 없이도 동작합니다. Claude 키는 고객 관점의 대화형 응답에만 필요합니다.

---

## 4. 부문 구성 및 현황

세 부문이 모두 합류하여 구현이 완료되었습니다.

### asset (자산)
- 반환일시금과 출국만기보험 마감 추적, 국민연금 예상 수령액 산정, 담보 계산, 송금 최적화, 대안신용 축적.
- tool 5개: `deadline_radar`, `pension_estimator`, `collateral_calc`, `remit_optimizer`, `credit_builder`.

### docs (서류행정)
- OCR 서류 파싱, 전세사기 및 비자 준법 심사, 정부 신청서 원클릭 자동작성.
- tool 3개: `perception_parse`, `compliance_reason`, `form_autofill`.

### fraud_guard (사기탐지)
- 재한 외국인 특화 4계층 이상거래 탐지 엔진을 탑재했습니다.
  - L1 결정론적 룰(출국 임박 잔액 인출, 심야 제3국 송금, 신규기기 고액 거래 등)
  - L2 국적과 비자 세그먼트별 Isolation Forest 정상분포 학습(오탐률 통제)
  - L3 룰축과 모델축의 앙상블 판정(정상, 추가 검토, 즉시 보류)
  - L4 Local-DIFFI 기반 피처 기여도 설명(판정 근거 제시)
- 출국기 계좌양도를 체류 만료일 기준 지수 가중으로 특화 탐지하며, 보류 거래에 대해 고객 모국어(베트남어, 네팔어)로 본인확인을 발송하고 강요와 원격제어 등 안전신호를 판별합니다.
- tool 4개: `register_baseline`, `score_transaction`, `detect_account_takeover`, `request_verification`.
- 기업 관점 관제 콘솔(`fraud_console/`)에서 보류 대기열, 판정 근거, AI 조사관 소견, 모국어 상담을 제공하며, 최종 승인과 차단은 사람 분석가가 결정합니다.

페르소나는 두 명으로 동결되어 있습니다. `minh` 응웬 반 민(베트남 E-9 근로자), `suman` 수만 라이(네팔 D-2 유학생).

---

## 5. 부문 확장 규약

새 부문은 `mcp_servers/` 아래에 규약에 맞는 폴더를 넣으면 서버 재시작 시 자동으로 연결됩니다. `registry.py`나 `backend/`를 직접 수정할 필요가 없습니다.

1. `CONTRACT.md`를 확인합니다. 입출력 규약을 어기면 통합이 깨집니다.
2. `mcp_servers/asset`을 자기 부문 영문명으로 복제합니다. 폴더명은 반드시 영문이어야 합니다.
3. `tools.py`의 함수를 자기 부문 tool로 교체합니다. 출력 4키 규약(`summary`, `detail`, `numbers`, `card`)을 지킵니다.
4. `schemas.py`의 `TOOL_SCHEMAS`도 함께 교체합니다.
5. `python -m pytest`로 검증합니다. 가드레일(`tests/test_contract.py`)이 새 부문을 자동 검사합니다.

`shared/registry.py`가 앱 시작 시 `mcp_servers/` 아래를 스캔하여 `TOOL_REGISTRY`가 있는 폴더를 모두 병합합니다. tool 실행과 LLM 스키마가 함께 합쳐져 대화 모드에 자동 노출되며, tool 이름이 겹치면 즉시 오류로 알립니다.

---

## 6. 온라인 배포

백엔드(FastAPI 서버)와 프론트(정적 파일)를 분리해 배포합니다.

### 백엔드 (Render)
1. GitHub에 push합니다.
2. Render에서 New Web Service로 본 저장소를 선택합니다.
3. Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Environment에 `ANTHROPIC_API_KEY`를 입력합니다(선택: `CLAUDE_MODEL_CHAT`, `CLAUDE_MODEL_DOCS`).

### 정적 프론트
- `web/config.js`의 `PROD_API`를 Render API URL로 설정합니다.
- `web/`와 `fraud_console/`를 정적 호스팅(Cloudflare Pages 등)에 올립니다. 빌드 과정 없이 그대로 서빙합니다.

---

## 보안 안내

`.env`는 절대 커밋하지 않습니다. 로컬 `.env`의 키가 외부에 노출된 적이 있으면(공유 또는 스크린샷 등) Anthropic 콘솔에서 키를 즉시 재발급하십시오.
