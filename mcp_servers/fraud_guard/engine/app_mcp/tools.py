"""app_mcp/tools.py — MCP tool 어댑터 (dict↔core). ★ mcp 의존 없음.

mcp_server.py 가 이 순수 함수들을 FastMCP tool 로 얇게 감싼다. 비즈니스 로직은
core(L1~L3)와 agent(L4)에 있고, 여기는 dict 경계 변환 + 위임만 한다.
파이프라인/검증기를 인자로 주입받으므로 서버 없이 단위 테스트가 가능하다.
"""
from __future__ import annotations

from agent.verification import Verifier
from app_mcp.schemas import assert_same_customer, profile_from_dict, result_to_dict, transaction_from_dict
from core.pipeline import FraudGuardPipeline


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
