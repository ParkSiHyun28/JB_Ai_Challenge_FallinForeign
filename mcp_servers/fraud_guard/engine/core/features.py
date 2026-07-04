"""core/features.py — ★ 피처의 단일 진실 원천 (불변 원칙 1).

합성생성(gen_synth)·학습(train_baseline)·추론(score)이 전부 이 모듈의
`FEATURES` 순서와 `to_feature_vector()` 만 사용한다.
피처 정의를 두 군데에 적으면 train/serve skew 가 발생하므로, 새 피처는
반드시 여기서만 추가한다.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from .schema import KST_OFFSET_MINUTES, CustomerProfile, Transaction

# 순서 고정 — IF 학습/추론/SHAP·DIFFI 라벨이 이 인덱스에 의존한다. 재배열 금지.
FEATURES: list[str] = [
    "amount_log",              # log1p(amount) — 금액의 우측 꼬리 압축
    "balance_drawdown_ratio",  # 0~1, 이번 거래 잔액 인출 비율
    "hour",                    # 0~23, 거래 로컬시각(tz_offset_minutes 적용, 기본 KST)
    "is_new_device",           # 0/1
    "corridor_match",          # 1 if 수취국 == 본국 else 0 (정상 송금 corridor)
    "tx_velocity_24h",         # 최근 24h 거래 수
    "days_to_residency_end",   # max(체류만료 - 기준일, 0) — 출국 임박도
]

N_FEATURES: int = len(FEATURES)

# 정직성 메모 (P1-4): is_new_device·corridor_match 는 정상 학습데이터에서 거의 상수
# (정상 new_device p≈0.02, corridor 준상수)라 IF 가 학습 중 이 축으로 '분기'하는 정보는
# 적다. 다만 추론 시엔 희소한 1(예: 신규기기) 이 고립되기 쉬워 anomaly score 에 기여는 한다
# ('무력'은 과장). 결정적 처리는 룰축(new_device_high_amount·corridor_mismatch)이 전담.
# → 두 축(IF=연속분포 / 룰=이산 외부상태신호)은 이 피처들에서 상관이 있어 완전 독립이 아니다.
#   OR 앙상블은 '독립 가정'이 아니라 보수적 결합(둘 중 상위)임을 분명히 한다(과대주장 금지).


def residency_days_signed(profile: CustomerProfile, today: Optional[date] = None) -> int:
    """기준일 대비 체류 만료까지 남은 일수 — **부호 보존**(음수=이미 만료=불법체류 의심).

    P1-5: 클립(max(..,0))은 '오늘 만료'와 '이미 만료'를 둘 다 0 으로 뭉개 정책 구분을
    잃는다. 룰축(rules.py)·takeover 는 이 부호 있는 값으로 '만료 후'를 별도 신호로 잡는다.
    """
    ref = today or date.today()
    return (profile.residency_end_date - ref).days


def days_to_residency_end(profile: CustomerProfile, today: Optional[date] = None) -> int:
    """IF 피처용: 만료까지 남은 일수, 음수는 0 클립.

    IF 피처는 비음수로 두어 저장 모델 분포와 호환을 유지한다(합성엔 음수 없음). '이미 만료'
    의 위험은 IF 피처가 아니라 룰축(residency_days_signed)이 전담한다(P1-5, 독립 두 축).
    """
    return max(residency_days_signed(profile, today), 0)


def local_hour_from_epoch(timestamp: float, tz_offset_minutes: int = KST_OFFSET_MINUTES) -> int:
    """POSIX epoch → 거래 발생지 로컬 벽시계 시(0~23). hour 산출의 단일 공식.

    UTC 가 아니라 로컬시 기준(P0-1). 합성생성(gen_synth)도 이 공식으로 epoch↔hour 를
    맞추므로(불변원칙 1), train/serve 가 동일 hour 규약을 공유한다.
    """
    return int(((timestamp + tz_offset_minutes * 60) // 3600) % 24)


def local_hour(tx: Transaction) -> int:
    """거래의 로컬시각 hour. tx 가 들고 있는 tz_offset_minutes(기본 KST) 사용."""
    return local_hour_from_epoch(tx.timestamp, tx.tz_offset_minutes)


def to_feature_vector(
    tx: Transaction,
    profile: CustomerProfile,
    today: Optional[date] = None,
) -> np.ndarray:
    """거래 1건 → 길이 7 고정 피처 벡터 (FEATURES 순서).

    today: 재현성을 위해 기준일을 주입할 수 있다(기본 date.today()).
        days_to_residency_end 가 기준일에 의존하므로, 합성·학습·서빙이
        같은 기준일을 쓰도록 호출부에서 고정하는 것을 권장한다.
    """
    corridor_match = 1.0 if tx.counterparty_country == profile.home_country else 0.0
    return np.array(
        [
            np.log1p(tx.amount),
            float(tx.balance_drawdown_ratio),
            float(local_hour(tx)),
            1.0 if tx.is_new_device else 0.0,
            corridor_match,
            float(tx.tx_velocity_24h),
            float(days_to_residency_end(profile, today)),
        ],
        dtype=float,
    )
