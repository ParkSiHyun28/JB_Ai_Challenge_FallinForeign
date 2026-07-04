"""core/config.py — yaml 설정의 타입화 로더 (불변원칙 2·3 준수).

임계값·페널티는 전부 config/*.yaml 에 있고(하드코딩 금지), 각 계층은 여기서
파싱한 dataclass 를 주입받는다. 단위 테스트는 dataclass 를 직접 만들어 주입할 수
있어(파일 의존 없이) 빠르게 돈다. mcp 의존 없음.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RULES = os.path.join(_ROOT, "config", "rules.yaml")
DEFAULT_THRESHOLDS = os.path.join(_ROOT, "config", "thresholds.yaml")


def _load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"config 파일 없음: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"config 형식 오류: {path} 최상위가 매핑(dict)이 아님 (got {type(raw).__name__})")
    return raw


def _get(d: dict, *keys, cast=None):
    """중첩 키를 안전하게 꺼낸다. 누락 시 전체 경로와 가용 키를 담은 친절한 에러(P2-1).

    raw KeyError 대신 'config 키 누락: rules.exit_drawdown.drawdown_min (확인: [...])' 형태로
    오타·구버전 yaml 을 즉시 식별하게 한다. cast 가 주어지면 형변환까지(잘못된 타입도 명확히)."""
    cur, path = d, []
    for k in keys:
        path.append(str(k))
        if not isinstance(cur, dict) or k not in cur:
            avail = sorted(cur) if isinstance(cur, dict) else f"<{type(cur).__name__}>"
            raise KeyError(f"config 키 누락: '{'.'.join(path)}' (확인 위치 키: {avail})")
        cur = cur[k]
    if cast is not None:
        try:
            return cast(cur)
        except (TypeError, ValueError) as e:
            raise ValueError(f"config 타입 오류: '{'.'.join(path)}'={cur!r} → {cast.__name__} 변환 실패 ({e})") from None
    return cur


# ==========================================================================
# L1 RuleLayer 파라미터 (config/rules.yaml)
# ==========================================================================
@dataclass(frozen=True)
class RuleParams:
    dday_window_days: int
    high_amount_krw: float
    night_hours: tuple
    penalty: dict          # rule_name -> penalty
    exit_drawdown_min: float
    rapid_velocity_min: int
    rapid_drawdown_min: float


def load_rule_params(path: str = DEFAULT_RULES) -> RuleParams:
    raw = _load_yaml(path)
    rules = _get(raw, "rules")
    return RuleParams(
        dday_window_days=_get(raw, "dday_window_days", cast=int),
        high_amount_krw=_get(raw, "high_amount_krw", cast=float),
        night_hours=tuple(int(h) for h in _get(raw, "night_hours")),
        penalty={name: _get(r, "penalty", cast=float) for name, r in rules.items()},
        exit_drawdown_min=_get(raw, "rules", "exit_drawdown", "drawdown_min", cast=float),
        rapid_velocity_min=_get(raw, "rules", "rapid_passthrough", "velocity_min", cast=int),
        rapid_drawdown_min=_get(raw, "rules", "rapid_passthrough", "drawdown_min", cast=float),
    )


# ==========================================================================
# L2/L3 임계값 파라미터 (config/thresholds.yaml)
# ==========================================================================
@dataclass(frozen=True)
class ThresholdParams:
    # L3 분위수(FPR 통제) — 모델 축
    review_q: float
    soft_block_q: float
    # L2 Isolation Forest
    if_n_estimators: int
    if_max_samples: int
    if_contamination: float
    if_random_state: int
    # L3 룰 축
    rule_review_score: float
    rule_soft_block_score: float
    # detect_account_takeover (지수 D-day)
    takeover_base: float
    takeover_k: float
    takeover_window_days: int
    takeover_soft_block_at: float
    # 모니터링
    min_samples_per_group: int


def load_threshold_params(path: str = DEFAULT_THRESHOLDS) -> ThresholdParams:
    raw = _load_yaml(path)
    mon = raw.get("monitoring", {})  # 선택 섹션
    return ThresholdParams(
        review_q=_get(raw, "baseline_quantiles", "review", cast=float),
        soft_block_q=_get(raw, "baseline_quantiles", "soft_block", cast=float),
        if_n_estimators=_get(raw, "isolation_forest", "n_estimators", cast=int),
        if_max_samples=_get(raw, "isolation_forest", "max_samples", cast=int),
        if_contamination=_get(raw, "isolation_forest", "contamination", cast=float),
        if_random_state=_get(raw, "isolation_forest", "random_state", cast=int),
        rule_review_score=_get(raw, "rule_action", "review_score", cast=float),
        rule_soft_block_score=_get(raw, "rule_action", "soft_block_score", cast=float),
        takeover_base=_get(raw, "dday_takeover", "base", cast=float),
        takeover_k=_get(raw, "dday_takeover", "k", cast=float),
        takeover_window_days=_get(raw, "dday_takeover", "window_days", cast=int),
        takeover_soft_block_at=_get(raw, "dday_takeover", "soft_block_at", cast=float),
        min_samples_per_group=int(mon.get("min_samples_per_group", 0)),
    )
