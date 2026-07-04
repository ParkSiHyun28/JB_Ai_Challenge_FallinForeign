"""core/decision.py — L3 DecisionEngine (OR 앙상블).

룰 축과 모델 축을 **각자 임계값과 비교**해 액션 레벨(allow<review<soft_block)을
정하고, 최종 액션 = max(두 축). 하나라도 상위면 상위 상태가 된다.

설계 의도(IMPLEMENTATION.md 3장 L3): 스케일이 다른 두 점수(룰 누적 vs IF 분위)의
**가중합을 쓰지 않는다** — 가중합은 스케일 정합을 가정해 왜곡된다. OR 은 그 가정을
하지 않는다(최적이라는 증거는 없음; 라벨 확보 후 PR-AUC 로 가중합·로지스틱과 비교 예정).

mcp 의존 없음.
"""
from __future__ import annotations

from typing import Optional

from .config import ThresholdParams, load_threshold_params

_NAME = {0: "allow", 1: "review", 2: "soft_block"}


class DecisionEngine:
    def __init__(self, params: ThresholdParams):
        self.p = params

    @classmethod
    def from_config(cls, path: Optional[str] = None) -> "DecisionEngine":
        return cls(load_threshold_params(path) if path else load_threshold_params())

    def rule_action(self, rule_score: float) -> int:
        """룰 누적 점수 → 액션 레벨 (분위수 아님, 페널티 스케일의 결정 규칙)."""
        if rule_score >= self.p.rule_soft_block_score:
            return 2
        if rule_score >= self.p.rule_review_score:
            return 1
        return 0

    def model_action(self, model_pctl: Optional[float]) -> int:
        """IF 분위(0~1) → 액션 레벨. 분위수가 FPR 을 통제한다. 미학습 그룹은 무신호."""
        if model_pctl is None:
            return 0
        if model_pctl >= self.p.soft_block_q:
            return 2
        if model_pctl >= self.p.review_q:
            return 1
        return 0

    def decide(self, rule_score: float, model_pctl: Optional[float],
               triggered: list[str]) -> tuple[float, str, dict]:
        """(risk_score, action, axes) 반환. action 은 두 축 OR(max)."""
        ra = self.rule_action(rule_score)
        ma = self.model_action(model_pctl)
        action = _NAME[max(ra, ma)]
        # risk_score 는 표시용 집계(결정은 위의 OR 로 끝남). 두 축 모두 0~1 → max.
        risk = max(rule_score, model_pctl if model_pctl is not None else 0.0)
        axes = {
            "rule_action": _NAME[ra],
            "model_action": _NAME[ma],
            "rule_score": round(rule_score, 3),
            "model_pctl": None if model_pctl is None else round(model_pctl, 4),
        }
        return risk, action, axes
