"""app_mcp/tools.py — MCP tool 어댑터 (dict↔core). ★ mcp 의존 없음.

mcp_server.py 가 이 순수 함수들을 FastMCP tool 로 얇게 감싼다. 비즈니스 로직은
core(L1~L3)와 agent(L4)에 있고, 여기는 dict 경계 변환 + 위임만 한다.
파이프라인/검증기를 인자로 주입받으므로 서버 없이 단위 테스트가 가능하다.
"""
from __future__ import annotations

from agent.verification import Verifier
from app_mcp.schemas import assert_same_customer, profile_from_dict, result_to_dict, transaction_from_dict
from core.pipeline import FraudGuardPipeline
from investigator_agent import ToolContext  # 증거/카드 단일 소스 재사용(mcp·anthropic 의존 없음)


def register_baseline(pipe: FraudGuardPipeline, segment_key: str, samples: list[dict]) -> dict:
    """samples: [{"transaction": {...}, "profile": {...}}, ...] → 그룹 IF 학습."""
    pairs = []
    for s in samples:
        tx, prof = transaction_from_dict(s["transaction"]), profile_from_dict(s["profile"])
        assert_same_customer(tx, prof)
        if prof.segment_key != segment_key:
            raise ValueError(f"sample segment mismatch: expected {segment_key!r}, got {prof.segment_key!r}")
        pairs.append((tx, prof))
    return pipe.register_baseline(segment_key, pairs)


def score_transaction(pipe: FraudGuardPipeline, transaction: dict, profile: dict) -> dict:
    tx, prof = transaction_from_dict(transaction), profile_from_dict(profile)
    assert_same_customer(tx, prof)
    r = pipe.score_transaction(tx, prof)
    return result_to_dict(r)


def detect_account_takeover(pipe: FraudGuardPipeline, transaction: dict, profile: dict) -> dict:
    tx, prof = transaction_from_dict(transaction), profile_from_dict(profile)
    assert_same_customer(tx, prof)
    r = pipe.detect_account_takeover(tx, prof)
    return result_to_dict(r)


def request_verification(pipe: FraudGuardPipeline, verifier: Verifier,
                         transaction: dict, profile: dict) -> dict:
    """의심 거래 점수화 후 모국어 본인확인 케이스 생성(시나리오 B 대응)."""
    tx = transaction_from_dict(transaction)
    prof = profile_from_dict(profile)
    assert_same_customer(tx, prof)
    r = pipe.score_transaction(tx, prof)
    case = verifier.request(tx, prof, r)
    case["score"] = result_to_dict(r)
    return case


def _alert_from_score(tx, prof, r) -> dict:
    """점수화 결과 → verification_chat 이 읽는 최소 알림 dict(게이트웨이 ALERTS 스키마의 부분집합)."""
    return {
        "id": tx.tx_id,
        "tx_id": tx.tx_id,
        "customer_id": prof.customer_id,
        "segment": prof.segment_key,
        "language": prof.language,
        "amount": tx.amount,
        "channel": tx.channel,
        "counterparty_country": tx.counterparty_country,
        "ip_country": tx.ip_country,
        "is_new_device": tx.is_new_device,
        "balance_drawdown_ratio": tx.balance_drawdown_ratio,
        "tx_velocity_24h": tx.tx_velocity_24h,
        "triggered_rules": list(r.triggered_rules),
        "action": r.action,
    }


def investigate_case(pipe: FraudGuardPipeline, agent, transaction: dict, profile: dict) -> dict:
    """의심 거래를 점수화한 뒤 '진짜' tool-calling 조사 에이전트로 조사 리포트를 만든다.

    agent = investigator_agent.InvestigatorAgent (내부에서 Claude 도구호출 루프 → 실제 API 필요).
    action/risk_score 는 core 가 이미 확정; 에이전트는 확인질문·비권위 가설·인계만 생성한다.
    agent 를 주입받으므로 가짜 에이전트로 API 없이 배선을 단위 테스트할 수 있다.
    """
    tx, prof = transaction_from_dict(transaction), profile_from_dict(profile)
    assert_same_customer(tx, prof)
    r = pipe.score_transaction(tx, prof)
    ctx = ToolContext.from_score(tx, prof, r)
    result = agent.investigate(ctx)
    return {
        "tx_id": result.tx_id,
        "score": result_to_dict(r),
        "submitted": result.submitted,
        "tool_calls": result.tool_calls,
        "turns": result.turns,
        "stop_reason": result.stop_reason,
        "model": result.model,
    }


def classify_verification_reply(pipe: FraudGuardPipeline, chat_agent, transaction: dict,
                                profile: dict, customer_reply: str, turn_index: int = 1) -> dict:
    """본인확인 대화의 고객 답변 1턴을 stateless 분류한다(모국어 다음 메시지·intent·라우팅 후보).

    다회전 상태(대화 히스토리)는 호출자(오케스트레이터)가 소유하고, 이 도구는 답변마다
    독립적으로 호출된다 — 그래서 단일 MCP 호출에 자연스럽게 맞는다(대화 루프를 감싸지 않음).
    chat_agent = agent.verification_chat.VerificationChatAgent (template 모드는 API 불필요).
    """
    tx, prof = transaction_from_dict(transaction), profile_from_dict(profile)
    assert_same_customer(tx, prof)
    r = pipe.score_transaction(tx, prof)
    alert = _alert_from_score(tx, prof, r)
    return chat_agent.process(alert, {"customer_reply": customer_reply}, turn_index=turn_index)
