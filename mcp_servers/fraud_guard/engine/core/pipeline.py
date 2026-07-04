"""core/pipeline.py — 4계층 조립 (L1 룰 + L2 IF + L3 OR + L4 설명 훅).

MCP Tool 매핑(어댑터는 app_mcp/tools.py 가 dict↔core 변환만; core 는 mcp 를 모름):
  register_baseline       → register_baseline()
  score_transaction       → score_transaction()
  detect_account_takeover → detect_account_takeover()
  (request_verification 은 agent/verification.py = Claude 모국어, 비동기)

모든 거래는 features.to_feature_vector(단일 진실 원천)로 변환된다.
재현성을 위해 today(기준일)를 파이프라인에 고정 주입할 수 있다.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

import numpy as np

from .baseline import BaselineStore
from .decision import DecisionEngine
from .explain import Explainer
from .features import to_feature_vector
from .rules import RuleLayer
from .schema import CustomerProfile, ScoreResult, Transaction
from .takeover import TakeoverDetector


class FraudGuardPipeline:
    def __init__(self, rules: Optional[RuleLayer] = None,
                 baseline: Optional[BaselineStore] = None,
                 decision: Optional[DecisionEngine] = None,
                 takeover: Optional[TakeoverDetector] = None,
                 explainer: Optional[Explainer] = None,
                 today: Optional[date] = None):
        self.rules = rules or RuleLayer.from_config()
        self.baseline = baseline or BaselineStore.from_config()
        self.decision = decision or DecisionEngine.from_config()
        self.takeover = takeover or TakeoverDetector.from_config()
        self.explainer = explainer or Explainer()
        self.today = today  # 고정 기준일(없으면 date.today())

    # --- MCP tool: register_baseline (L2 그룹 학습) ---
    def register_baseline(self, segment_key: str,
                          normal_txs: Iterable[tuple[Transaction, CustomerProfile]]) -> dict:
        X = np.vstack([to_feature_vector(tx, p, self.today) for tx, p in normal_txs])
        return self.baseline.fit(segment_key, X)

    # --- MCP tool: score_transaction (L1 + L2 실시간 → L3) ---
    def score_transaction(self, tx: Transaction, profile: CustomerProfile) -> ScoreResult:
        rule_score, triggered = self.rules.evaluate(tx, profile, self.today)
        x = to_feature_vector(tx, profile, self.today)
        model_pctl = self.baseline.percentile(profile.segment_key, x)
        risk, action, axes = self.decision.decide(rule_score, model_pctl, triggered)

        result = ScoreResult(
            tx_id=tx.tx_id,
            rule_score=round(rule_score, 3),
            model_score=round(model_pctl, 4) if model_pctl is not None else None,  # 미학습 그룹 = None(P1-6)
            risk_score=round(risk, 3),
            triggered_rules=list(triggered),
            action=action,
            explanation={"axes": axes},
        )
        # 보류 거래에만 피처 기여 설명(비동기로 빼도 됨). Local-DIFFI(faithful) 우선, z-편차 폴백(P1-2).
        if action == "soft_block":
            feats, method = self.explainer.explain_faithful(self.baseline, profile.segment_key, x)
            result.explanation["features"] = feats
            result.explanation["explain_method"] = method
        return result

    # --- MCP tool: detect_account_takeover (출국기 지수 D-day 가중) ---
    def detect_account_takeover(self, tx: Transaction, profile: CustomerProfile) -> ScoreResult:
        result = self.score_transaction(tx, profile)
        return self.takeover.apply(result, profile, self.today)
