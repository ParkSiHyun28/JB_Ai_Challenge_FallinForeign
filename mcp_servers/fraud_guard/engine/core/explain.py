"""core/explain.py — L4 설명 (보류 거래에만, 경량·shap 비의존).

"왜 막았는가"를 피처별 기여로 근사한다. 보류(soft_block)된 거래에만 호출되므로
실시간 결제 경로 밖이다(IMPLEMENTATION.md L4: 비동기).

두 방법(정직성 P1-2):
  1) local_diffi — **IF 의 실제 분리경로** 기반 기여(faithful). 이 인스턴스가 각 트리에서
     어떤 피처로, 얼마나 빨리(얕은 깊이) 고립됐는지를 1/(depth+1) 누적으로 집계해 정규화.
     z-편차와 달리 모델의 판단 메커니즘을 반영한다. (Local-DIFFI 계열 근사 — 정규화/형태는
     Carletti 2019 의 단순화판. '분리경로 기여'로 정직하게 라벨.)
  2) explain (z-편차) — (x-μ)/σ 크기 순위. 단변량 '참고' 지표일 뿐 IF 충실 설명 아님.
     local_diffi 가 불가(준상수 트리 등)할 때 폴백.

경량·결정론적. shap 미설치에도 동작(트리 구조 직접 순회). max_features=1.0(기본) 가정 —
트리 feature 인덱스가 FEATURES 와 1:1. (config 에서 max_features 를 바꾸면 매핑 보정 필요.)
"""
from __future__ import annotations

import numpy as np

from .features import FEATURES

_LEAF = -1  # sklearn tree: 리프 노드의 children_left/right == -1 (TREE_LEAF)


class Explainer:
    def explain(self, store, segment_key: str, x: np.ndarray, top_k: int = 4) -> dict:
        """피처별 표준화 편차 상위 top_k 를 {feature: z} 로 반환 (참고 지표, 충실 아님)."""
        if not store.has(segment_key):
            return {"note": "unfitted group — no baseline to explain against"}
        scaler = store.artifacts(segment_key)["scaler"]
        z = scaler.transform(np.asarray(x, dtype=float).reshape(1, -1))[0]
        ranked = sorted(zip(FEATURES, z), key=lambda kv: abs(kv[1]), reverse=True)
        return {name: round(float(val), 3) for name, val in ranked[:top_k]}

    def local_diffi(self, store, segment_key: str, x: np.ndarray, top_k: int = 4) -> dict:
        """IF 분리경로 기반 피처 기여(0~1 정규화) 상위 top_k. faithful 설명(P1-2).

        각 트리에서 x 가 루트→리프로 내려가며 분기한 노드의 split 피처에 1/(depth+1) 을
        누적(얕을수록 빨리 고립 = 더 중요). 전 트리 합산 후 합=1 로 정규화.
        미학습 그룹은 note, 기여가 0(준상수)면 빈 dict → 호출부가 폴백 판단.
        """
        if not store.has(segment_key):
            return {"note": "unfitted group — no baseline to explain against"}
        art = store.artifacts(segment_key)
        scaler, model = art["scaler"], art["model"]
        xs = scaler.transform(np.asarray(x, dtype=float).reshape(1, -1))[0]
        imp = np.zeros(len(FEATURES), dtype=float)
        for est in model.estimators_:
            t = est.tree_
            node, depth = 0, 0
            while t.children_left[node] != _LEAF:            # 내부 노드인 동안
                f = int(t.feature[node])
                if 0 <= f < len(imp):
                    imp[f] += 1.0 / (depth + 1.0)            # 얕은 split = 빠른 고립 = 큰 기여
                node = (t.children_left[node] if xs[f] <= t.threshold[node]
                        else t.children_right[node])
                depth += 1
        total = imp.sum()
        if total <= 0:
            return {}
        imp /= total
        ranked = sorted(zip(FEATURES, imp), key=lambda kv: kv[1], reverse=True)
        return {name: round(float(v), 3) for name, v in ranked[:top_k] if v > 0}

    def explain_faithful(self, store, segment_key: str, x: np.ndarray, top_k: int = 4):
        """(설명 dict, method) 반환. Local-DIFFI(faithful) 우선, 실패 시 z-편차 폴백.

        method ∈ {"local_diffi", "zdev", "none"} — 소비자(콘솔)가 라벨을 정확히 붙이게 한다.
        """
        if not store.has(segment_key):
            return {"note": "unfitted group — no baseline to explain against"}, "none"
        try:
            d = self.local_diffi(store, segment_key, x, top_k)
            if d and "note" not in d:
                return d, "local_diffi"
        except Exception:
            pass
        return self.explain(store, segment_key, x, top_k), "zdev"
