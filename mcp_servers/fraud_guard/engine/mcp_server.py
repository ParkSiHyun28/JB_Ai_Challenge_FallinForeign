"""mcp_server.py — fraud-guard MCP 진입점 (로직 없음).

core 파이프라인(L1~L3) + agent 모국어 검증(L4) + 진짜 tool-calling 에이전트를
app_mcp.tools 어댑터로 감싸 6개 MCP tool 로 노출한다. 로직은 core/·agent/·
investigator_agent/ 에만 있고 여기는 바인딩+감사로그만.
  기본 4: register_baseline · score_transaction · detect_account_takeover · request_verification
  추가 2: investigate_case(진짜 조사 에이전트, 실제 API 필요) ·
          classify_verification_reply(턴별 모국어 분류기, template=API불필요)

실행: pip install "mcp[cli]" scikit-learn     # 모델은 학습돼 있으면 로드만
      (필요 시 오프라인 학습) python scripts/train_baseline.py
      python mcp_server.py
환경변수: FRAUDGUARD_VERIFY_MODE = template(기본) | claude | openai  (모국어 메시지 생성 엔진)
         - claude : ANTHROPIC_API_KEY
         - openai : 무료 LLM(OpenAI 호환) — FRAUDGUARD_LLM_BASE_URL / _API_KEY / _MODEL
                    예) Groq·Gemini·Ollama. 추가 SDK 불필요(stdlib urllib), 실패 시 템플릿 폴백.
         FRAUDGUARD_MODEL=data/models/baseline.joblib, FRAUDGUARD_AUDIT=audit.jsonl
"""
from __future__ import annotations

import json
import os
import time

from agent.verification import Verifier
from agent.verification_chat import VerificationChatAgent
from app_mcp import tools
from core.baseline import BaselineStore
from core.pipeline import FraudGuardPipeline
from investigator_agent import InvestigatorAgent

try:  # MCP SDK 미설치여도 어댑터 로직 import 는 가능(테스트 보호)
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

_ROOT = os.path.dirname(os.path.abspath(__file__))
AUDIT_LOG = os.environ.get("FRAUDGUARD_AUDIT", os.path.join(_ROOT, "audit.jsonl"))
MODEL_PATH = os.environ.get("FRAUDGUARD_MODEL", os.path.join(_ROOT, "data", "models", "baseline.joblib"))


def _build_pipeline() -> FraudGuardPipeline:
    """저장된 베이스라인이 있으면 로드만(학습/서빙 분리), 없으면 빈 파이프라인."""
    if os.path.exists(MODEL_PATH):
        return FraudGuardPipeline(baseline=BaselineStore.load(MODEL_PATH))
    return FraudGuardPipeline()


PIPE = _build_pipeline()
VERIFIER = Verifier(mode=os.environ.get("FRAUDGUARD_VERIFY_MODE", "template"))

# 진짜 tool-calling 조사 에이전트 — investigate_case tool 안에서 Claude 도구호출 루프를 돈다.
# 실제 API 필요(ANTHROPIC_API_KEY); MCP tool 안의 sub-agent 구조라 느리고 키 의존적이다.
AGENT_MODEL = os.environ.get("FRAUDGUARD_AGENT_MODEL", "claude-opus-4-8")
INVESTIGATOR_AGENT = InvestigatorAgent(model=AGENT_MODEL)
# 턴별 모국어 분류기(대화 상태 없음) — classify_verification_reply tool 이 답변마다 호출.
# template 모드는 API 불필요(결정론 안전가드+템플릿), claude/openai 모드면 LLM 사용.
VERIFICATION_CHAT = VerificationChatAgent(
    mode=os.environ.get("FRAUDGUARD_CHAT_MODE",
                        os.environ.get("FRAUDGUARD_VERIFY_MODE", "template")),
    model=os.environ.get("FRAUDGUARD_LLM_MODEL", "claude-sonnet-4-6"))


def _audit(event: dict) -> None:
    """append-only 감사 추적(모든 판단 기록)."""
    event["logged_at"] = time.time()
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


if FastMCP is not None:
    mcp = FastMCP("fraud-guard")

    @mcp.tool()
    def register_baseline(segment_key: str, samples: list[dict]) -> dict:
        """(국적×비자) 그룹 정상 거래로 Isolation Forest baseline 학습.
        samples=[{"transaction":{...}, "profile":{...}}, ...]"""
        out = tools.register_baseline(PIPE, segment_key, samples)
        _audit({"tool": "register_baseline", **out})
        return out

    @mcp.tool()
    def score_transaction(transaction: dict, profile: dict) -> dict:
        """거래 1건 실시간 점수화 (L1 룰 + L2 IF → L3 OR 앙상블)."""
        out = tools.score_transaction(PIPE, transaction, profile)
        _audit({"tool": "score_transaction", **out})
        return out

    @mcp.tool()
    def detect_account_takeover(transaction: dict, profile: dict) -> dict:
        """출국 임박 지수 D-day 가중으로 계좌양도 의심도 산출 (시나리오 A)."""
        out = tools.detect_account_takeover(PIPE, transaction, profile)
        _audit({"tool": "detect_account_takeover", **out})
        return out

    @mcp.tool()
    def request_verification(transaction: dict, profile: dict) -> dict:
        """의심 거래 점수화 + 고객 모국어 본인확인 메시지 생성 (시나리오 B)."""
        out = tools.request_verification(PIPE, VERIFIER, transaction, profile)
        _audit({"tool": "request_verification", "tx_id": out.get("tx_id"),
                "action": out["score"]["action"], "language": out.get("language")})
        return out

    @mcp.tool()
    def investigate_case(transaction: dict, profile: dict) -> dict:
        """의심 거래를 점수화 후 '진짜' tool-calling 조사 에이전트로 조사한다.
        Claude 가 read-only 도구를 스스로 호출해 근거를 모으고, 고객 모국어 확인질문·
        비권위 가설·인계를 제출한다. 판정(action)은 core 확정 — 바꾸지 않는다.
        ⚠️ 실제 Claude API 필요(ANTHROPIC_API_KEY) — MCP tool 안의 sub-agent 루프(느림)."""
        out = tools.investigate_case(PIPE, INVESTIGATOR_AGENT, transaction, profile)
        _audit({"tool": "investigate_case", "tx_id": out.get("tx_id"),
                "turns": out.get("turns"), "model": out.get("model")})
        return out

    @mcp.tool()
    def classify_verification_reply(transaction: dict, profile: dict,
                                    customer_reply: str, turn_index: int = 1) -> dict:
        """본인확인 대화의 고객 답변 1턴을 stateless 분류한다(모국어 다음 메시지·intent·
        라우팅 후보). 대화 상태는 오케스트레이터가 소유하고 답변마다 이 도구를 호출한다.
        강요·원격제어·피싱 신호는 결정론 안전가드가 먼저 잡는다(LLM 뒤집기 불가)."""
        out = tools.classify_verification_reply(PIPE, VERIFICATION_CHAT, transaction, profile,
                                                customer_reply, turn_index)
        _audit({"tool": "classify_verification_reply", "tx_id": out.get("tx_id"),
                "intent": out.get("detected_intent"), "next_state": out.get("next_state")})
        return out


if __name__ == "__main__":
    if FastMCP is None:
        raise SystemExit("pip install 'mcp[cli]' scikit-learn anthropic 후 실행하세요.")
    mcp.run()
