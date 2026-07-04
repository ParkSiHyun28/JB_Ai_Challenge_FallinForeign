"""core/takeover.py — detect_account_takeover (출국기 계좌양도 특화).

체류 만료가 가까울수록 양도 위험을 **지수 감쇠**로 가중한다(선형 아님):
    boost = base * exp(-k * days_left)   (0 <= days_left <= window 에서만)
D-0 에 최대(base), 멀어질수록 급감.

근거 상태(IMPLEMENTATION.md): 비선형 방향은 합리적이나 함수형태·k·base 는 가정.
순환논리를 피하려 시나리오 A 로 '튜닝'하지 않고, k 민감도 분석으로 강건성만 주장.
모든 수치는 config/thresholds.yaml(dday_takeover). mcp 의존 없음.

한계·중복 (정직, P1-3): IF 피처에 days_to_residency_end 가 이미 있어, '창 안(0~window)'
구간에서 boost 는 IF/룰과 신호가 겹친다. sensitivity 의 k-곡선이 평탄한 것도 이 때문
(다른 축이 이미 soft_block → boost 의 한계효과 미미). base(≤0.25) 단독으론 soft_block_at
(0.70)을 못 넘으므로 boost 가 정상 거래를 단독 승격시키지 못한다(설계상 보수적).
→ 그럼에도 유지하는 이유: (1) 임계 근처 경계 케이스의 미세 가중, (2) '이미 만료(음수)'
는 IF 피처가 클립(0)으로 못 보는 신호라 boost 가 최대가중으로 전담(P1-5) = 비중복 역할.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from typing import Optional

from .config import ThresholdParams, load_threshold_params
from .features import residency_days_signed
from .schema import CustomerProfile, ScoreResult


class TakeoverDetector:
    def __init__(self, params: ThresholdParams):
        self.p = params

    @classmethod
    def from_config(cls, path: Optional[str] = None) -> "TakeoverDetector":
        return cls(load_threshold_params(path) if path else load_threshold_params())

    def boost(self, days_left: Optional[int]) -> float:
        """지수 D-day 가중치. 이미 만료(음수)는 최고위험 → D-0 동일 최대 가중. 창 밖이면 0."""
        if days_left is None:
            return 0.0
        if days_left < 0:                                  # 만료 후(불법체류 의심) = 최대 가중(P1-5)
            return self.p.takeover_base
        if days_left > self.p.takeover_window_days:
            return 0.0
        return self.p.takeover_base * math.exp(-self.p.takeover_k * days_left)

    def apply(self, result: ScoreResult, profile: CustomerProfile,
              today: Optional[date] = None) -> ScoreResult:
        """기존 ScoreResult 에 D-day boost 적용 → risk 상향, 임계 초과 시 soft_block 승격."""
        days_left = residency_days_signed(profile, today)  # 부호 보존(음수=만료 후), P1-5
        b = self.boost(days_left)
        if b <= 0:
            return result
        boosted = min(result.risk_score + b, 1.0)
        # P2-5: 입력 ScoreResult 를 변형하지 않고 새 인스턴스를 반환(불변 → 별칭 버그 예방).
        explanation = dict(result.explanation or {})
        explanation["takeover_boost"] = round(b, 3)
        explanation["days_to_residency_end"] = days_left
        action, triggered = result.action, list(result.triggered_rules)
        if boosted >= self.p.takeover_soft_block_at and action != "soft_block":
            action = "soft_block"
            if "exit_takeover_boost" not in triggered:
                triggered.append("exit_takeover_boost")
        return replace(result, risk_score=round(boosted, 3), action=action,
                       triggered_rules=triggered, explanation=explanation)
