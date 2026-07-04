"""core/baseline.py — L2 BaselineStore (그룹별 Isolation Forest + 분위수).

segment_key(국적:비자)별로 정상 거래만 학습한 IF 를 보관한다.
푸는 것: 오탐(false positive) — "베트남 E-9 정상"과 "네팔 D-2 정상"은 다른 분포다.

핵심(IMPLEMENTATION.md 5장): 점수의 임계값은 **정상 점수의 분위수**로 정한다.
분위수는 분포 형태와 무관하게 FPR(오탐)만 통제한다. percentile(x)=정상 중 x보다
덜 이상한 비율 → percentile>=0.99 면 "정상의 상위 1%만큼 이상" = FPR≈1%.
Recall 은 라벨로 PR커브에서 별도 측정한다(여기서 보장하지 않음).

학습/서빙 분리(불변원칙 4): fit 은 오프라인(scripts/train_baseline), 서버는 load 만.
저장 시 scaler+model+정상점수분포+임계값+seed 를 함께 묶는다.
mcp 의존 없음. score 계산은 features.to_feature_vector 로 만든 벡터를 입력받는다.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np

from .config import ThresholdParams, load_threshold_params

try:  # sklearn 은 런타임 의존성 — 미설치여도 import 는 통과(테스트 수집 보호)
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
except ImportError:  # pragma: no cover
    IsolationForest = None
    StandardScaler = None


class BaselineStore:
    """segment_key -> {scaler, model, scores_sorted, thresholds, n}."""

    def __init__(self, params: ThresholdParams):
        self.p = params
        self._models: dict[str, dict] = {}

    @classmethod
    def from_config(cls, path: Optional[str] = None) -> "BaselineStore":
        return cls(load_threshold_params(path) if path else load_threshold_params())

    # --- 학습 (오프라인) ---
    def fit(self, segment_key: str, X_normal: np.ndarray) -> dict:
        """정상 거래 피처행렬로 그룹 IF 학습 + 정상 점수 분위수 임계 유도."""
        if IsolationForest is None:
            raise RuntimeError("pip install scikit-learn 필요")
        X = np.asarray(X_normal, dtype=float)
        if X.ndim != 2 or len(X) == 0:
            raise ValueError("X_normal 은 (n, n_features) 비어있지 않은 행렬이어야 함")
        scaler = StandardScaler().fit(X)
        max_samples = min(self.p.if_max_samples, len(X))  # IF 원논문 ψ≈256
        model = IsolationForest(
            n_estimators=self.p.if_n_estimators,
            max_samples=max_samples,
            contamination=self.p.if_contamination,
            random_state=self.p.if_random_state,
        ).fit(scaler.transform(X))

        scores = self._anomaly_scores(scaler, model, X)  # 높을수록 이상
        self._models[segment_key] = {
            "scaler": scaler,
            "model": model,
            "scores_sorted": np.sort(scores),
            "n": int(len(X)),
            # 표시용 근사(사람이 읽는 '점수값'). 실제 결정·FPR 은 percentile_of_scores(ECDF)로
            # 통일(P0-4). np.quantile 임계로 직접 결정하지 말 것 — 배포 규칙과 미세 불일치.
            "thresholds": {
                "review": float(np.quantile(scores, self.p.review_q)),
                "soft_block": float(np.quantile(scores, self.p.soft_block_q)),
            },
        }
        return {
            "segment_key": segment_key,
            "n_samples": int(len(X)),
            "max_samples": int(max_samples),
            "thresholds": self._models[segment_key]["thresholds"],
            "low_sample": len(X) < self.p.min_samples_per_group,  # 꼬리 분위수 추정 불확실 경고
        }

    @staticmethod
    def _anomaly_scores(scaler, model, X: np.ndarray) -> np.ndarray:
        # score_samples: 높을수록 정상 → 부호 반전(높을수록 이상)
        return -model.score_samples(scaler.transform(np.asarray(X, dtype=float)))

    # --- 서빙 (실시간) ---
    def has(self, segment_key: str) -> bool:
        return segment_key in self._models

    def anomaly_score(self, segment_key: str, x: np.ndarray) -> float:
        m = self._models[segment_key]
        return float(self._anomaly_scores(m["scaler"], m["model"], x.reshape(1, -1))[0])

    def percentile_of_scores(self, segment_key: str, scores) -> np.ndarray:
        """이미 계산된 이상점수 배열 → 학습 정상분포 대비 ECDF 분위(0~1) 배열.

        ★ FPR 결정의 단일 정의(P0-4): 배포 결정(decision.model_action)·민감도·외부검증·
        부트스트랩이 모두 이 ECDF 순위(searchsorted)를 쓴다. np.quantile 임계와 섞지 말 것
        ("검증한 FPR == 배포 FPR"). thresholds(np.quantile)는 사람이 읽는 표시용 근사일 뿐.
        """
        ss = self._models[segment_key]["scores_sorted"]
        s = np.asarray(scores, dtype=float)
        return np.searchsorted(ss, s, side="right") / len(ss)

    def percentile(self, segment_key: str, x: np.ndarray) -> Optional[float]:
        """x 의 이상 점수가 정상 분포에서 차지하는 분위(0~1). 미학습 그룹은 None."""
        if segment_key not in self._models:
            return None
        s = self.anomaly_score(segment_key, x)
        return float(self.percentile_of_scores(segment_key, [s])[0])

    def thresholds(self, segment_key: str) -> dict:
        return self._models[segment_key]["thresholds"]

    def artifacts(self, segment_key: str) -> dict:
        """explain 등 내부 소비자용(scaler/model 접근)."""
        return self._models[segment_key]

    # --- 저장/로드 (model+scaler+분포+임계+seed 묶음) ---
    @staticmethod
    def _sha256(path: str) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def save(self, path: str, data_version: str = "") -> None:
        import joblib
        joblib.dump({
            "params": self.p,
            "models": self._models,
            "seed": self.p.if_random_state,
            "data_version": data_version,
        }, path)
        # P2-2: 무결성 체크섬 사이드카(심층방어). joblib=pickle 이라 변조/손상 탐지용.
        with open(path + ".sha256", "w", encoding="utf-8") as f:
            f.write(self._sha256(path))

    @classmethod
    def load(cls, path: str, verify: bool = True) -> "BaselineStore":
        import joblib
        # P2-2: 사이드카 체크섬이 있으면 역직렬화 '전에' 무결성 검증(pickle 임의코드 실행 방어).
        sig = path + ".sha256"
        if verify and os.path.exists(sig):
            expected = open(sig, encoding="utf-8").read().strip()
            actual = cls._sha256(path)
            if expected != actual:
                raise ValueError(
                    f"baseline 무결성 검증 실패: {path}\n  기대 {expected[:16]}… ≠ 실제 {actual[:16]}… "
                    "(모델 변조/손상 의심 — train_baseline.py 재실행으로 재생성).")
        blob = joblib.load(path)
        store = cls(blob["params"])
        store._models = blob["models"]
        return store
