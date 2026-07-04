"""팀원 사기탐지 엔진(engine/) 브리지.

engine/ 은 팀원이 만든 원본 코드를 그대로 둔 것이다(수정 최소화). 그 코드는 내부에서
`from core.pipeline import ...` 처럼 top-level 패키지(core/agent/contracts/app_mcp)로 서로를
import 한다. 학습모델 baseline.joblib 도 피클에 `core.*` 클래스를 참조한다. 그래서 engine/
디렉터리를 sys.path 에 얹어 그 이름들이 top-level 로 잡히게 한다. 우리 repo 에는 같은 이름의
top-level 패키지가 없어 충돌하지 않는다.

파이프라인과 검증기는 첫 호출 때 1회 빌드해 캐시한다(모델 로드가 무겁기 때문).
LLM 없이 도는 template 모드가 기본이라 API 키가 없어도 완전히 동작한다.
"""
from __future__ import annotations

import os
import sys
import warnings

_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")
_MODEL_PATH = os.path.join(_ENGINE_DIR, "data", "models", "baseline.joblib")

if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

# 시연 기준일(민 출국 D-90). 엔진 D-day 계산을 재현 가능하게 고정 주입한다.
from datetime import date  # noqa: E402
_DEMO_TODAY = date(2026, 10, 3)

_pipe = None
_verifier = None
_load_error = None


def _build():
    """엔진 파이프라인과 검증기를 1회 빌드해 캐시. 실패해도 앱은 죽지 않는다(사유만 기록)."""
    global _pipe, _verifier, _load_error
    if _pipe is not None or _load_error is not None:
        return
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from core.pipeline import FraudGuardPipeline
            from core.baseline import BaselineStore
            from agent.verification import Verifier

            baseline = BaselineStore.load(_MODEL_PATH, verify=True)
            _pipe = FraudGuardPipeline(baseline=baseline, today=_DEMO_TODAY)
            _verifier = Verifier(mode="template")  # 라이브 시연 안정: 결정론 템플릿
    except Exception as e:  # 모델/의존성 문제 시 엔진 없이 안전 응답으로 폴백
        _load_error = f"{type(e).__name__}: {e}"


def available() -> bool:
    _build()
    return _pipe is not None


def load_error() -> str | None:
    _build()
    return _load_error


def segments() -> list:
    """학습된 세그먼트 키 목록(예 ['NP:D-2', 'VN:E-9'])."""
    _build()
    if _pipe is None:
        return []
    return sorted(_pipe.baseline._models.keys())


def score(profile: dict, tx: dict) -> dict:
    """거래 1건 채점. 엔진 원시 결과 dict 반환(rule_score/model_score/risk_score/action/...)."""
    _build()
    from app_mcp.tools import score_transaction
    return score_transaction(_pipe, tx, profile)


def takeover(profile: dict, tx: dict) -> dict:
    """계좌양도 탐지(출국기 D-day 지수 가중 적용). 엔진 원시 결과 dict 반환."""
    _build()
    from app_mcp.tools import detect_account_takeover
    return detect_account_takeover(_pipe, tx, profile)


def verify(profile: dict, tx: dict) -> dict:
    """보류 거래에 모국어 본인확인 케이스 생성. 엔진 원시 case dict 반환."""
    _build()
    from app_mcp.tools import request_verification
    return request_verification(_pipe, _verifier, tx, profile)


def investigate(profile: dict, tx: dict) -> dict:
    """AI 조사관 브리핑 생성. 판정을 바꾸지 않고 증거카드, 케이스 요약, 의심 유형,
    권고 조치, 신뢰도, 확인 질문을 만든다(전부 코드 결정론, 라이브 안전).

    반환(InvestigationOutput dict): case_summary, key_evidence, verification_questions,
    suspected_type, recommended_next_action, confidence 등.
    """
    _build()
    from app_mcp.schemas import transaction_from_dict, profile_from_dict
    from agent.investigate import Investigator
    t = transaction_from_dict(tx)
    p = profile_from_dict(profile)
    r = _pipe.detect_account_takeover(t, p)
    inv = Investigator(mode="template")
    ev = inv.evidence_from_score(t, p, r)
    return inv.investigate_evidence(ev)


def chat_turn(alert: dict, reply: str, turn_index: int = 1) -> dict:
    """고객 본인확인 답변 1턴 의도분류. 안전신호(강요/원격제어/사기스크립트)는 결정론 우선.

    alert 는 대상 케이스 요약 dict(tx_id/customer_id/language/amount/channel/
    counterparty_country/is_new_device/balance_drawdown_ratio/triggered_rules/verification).
    반환: detected_intent, next_state, analyst_summary_ko, customer_next_message,
    operator_checklist 등. 판정을 다시 점수화하지 않는다(결정은 분석가 몫).
    """
    _build()
    from agent.verification_chat import VerificationChatAgent
    agent = VerificationChatAgent(mode="template")  # 라이브 안정: 결정론 분류 + 템플릿 문구
    return agent.process(alert, {"customer_reply": reply}, turn_index=turn_index)


def explanation_features(result: dict) -> dict:
    """엔진 결과에서 Local-DIFFI 피처 기여 dict 를 꺼낸다(soft_block 일 때만 존재)."""
    return (result.get("explanation") or {}).get("features") or {}


def baseline_thresholds(segment_key: str) -> dict | None:
    """세그먼트의 학습된 임계(review/soft_block 분위)와 표본 수. 없으면 None."""
    _build()
    if _pipe is None or segment_key not in _pipe.baseline._models:
        return None
    m = _pipe.baseline._models[segment_key]
    return {
        "review": m["thresholds"].get("review"),
        "soft_block": m["thresholds"].get("soft_block"),
    }
