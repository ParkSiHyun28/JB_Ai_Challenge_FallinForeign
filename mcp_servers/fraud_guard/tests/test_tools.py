"""사기탐지 tool 단위 테스트. 진짜 엔진(engine/) 감싼 tool 의 행동을 검증한다.

옛 mock(가중치 합, 고정 94점)이 아니라 실제 4계층 ML 엔진 결과를 확인한다. 정확한
점수는 모델에 달려 있으므로 값을 못박기보다 판정(action)과 4키 규약, 근거 존재를 본다.
엔진(scikit-learn/joblib/모델)이 없으면 안전 폴백을 검증한다.
"""
import pytest

from mcp_servers.fraud_guard import _engine
from mcp_servers.fraud_guard.tools import (
    score_transaction,
    detect_account_takeover,
    request_verification,
    register_baseline,
)

ENGINE = _engine.available()
requires_engine = pytest.mark.skipif(not ENGINE, reason=f"엔진 미로드: {_engine.load_error()}")

FOUR_KEYS = {"summary", "detail", "numbers", "card"}


def _assert_contract(r: dict):
    assert set(r.keys()) == FOUR_KEYS
    assert isinstance(r["summary"], str) and r["summary"]
    assert isinstance(r["detail"], str)
    assert isinstance(r["numbers"], dict)
    assert r["card"] is None or set(r["card"]) == {"icon", "head", "body", "metric"}
    if r["card"]:
        assert r["card"]["icon"] == ""  # 이모지 금지


def test_all_tools_keep_4key_contract():
    for r in (score_transaction("minh"), detect_account_takeover("minh"),
              request_verification("minh"), register_baseline("minh"),
              score_transaction("suman"), register_baseline("suman")):
        _assert_contract(r)


@requires_engine
def test_score_transaction_minh_hero_is_soft_block():
    r = score_transaction("minh")
    n = r["numbers"]
    assert n["action"] == "soft_block"       # 940만 계좌양도 = 즉시 보류
    assert n["score"] >= 80                   # 위험 점수 상단
    assert n["engine_available"] is True
    assert r["card"] is not None


@requires_engine
def test_score_transaction_salary_is_allow():
    r = score_transaction("minh", tx_id="TX-MINH-2701")  # 급여 입금
    assert r["numbers"]["action"] == "allow"
    assert r["card"] is None


@requires_engine
def test_score_transaction_night_remittance_triggers_rules():
    r = score_transaction("minh", tx_id="TX-MINH-1001")  # 심야 제3국 송금
    rules = r["numbers"]["triggered_rules"]
    assert "night_remittance" in rules or "corridor_mismatch" in rules


@requires_engine
def test_detect_account_takeover_minh_suspected():
    r = detect_account_takeover("minh")
    assert r["numbers"]["takeover_suspected"] is True
    assert r["numbers"]["action"] == "soft_block"


@requires_engine
def test_request_verification_minh_native_language():
    r = request_verification("minh")
    n = r["numbers"]
    assert n["delivered"] is True
    assert n["language"] == "vi"             # 베트남 페르소나 = 베트남어
    assert n["language_ko"] == "베트남어"


@requires_engine
def test_register_baseline_minh_segment_trained():
    r = register_baseline("minh")
    n = r["numbers"]
    assert n["segment_key"] == "VN:E-9"
    assert n["trained"] is True
    assert 0 < n["soft_block_threshold"] < 1


@requires_engine
def test_register_baseline_suman_segment_trained():
    r = register_baseline("suman")
    assert r["numbers"]["segment_key"] == "NP:D-2"
    assert r["numbers"]["trained"] is True


def test_unknown_persona_raises():
    with pytest.raises(Exception):
        score_transaction("no_such_persona")
