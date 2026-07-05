"""mcp_http_gateway.py — HTTP 게이트웨이 + 이상거래 모니터링 콘솔 백엔드 (stdlib만).

두 역할:
  1) MCP tool 4종을 JSON 엔드포인트로 노출 (오케스트레이터/수동 재심사용).
  2) 실무자(FDS/AML 분석가) 콘솔용 알림 큐 + 케이스 처리 + 운영 KPI.

알림 큐는 합성 거래(data/synth/synth_all.csv)를 파이프라인으로 채점해 '보류/검토'로
걸린 건들로 구성한다(진짜 이상치 + 분위수 오탐 일부 = 실제 트리아지와 동일한 혼합).
로직은 core/agent 에만, 여기는 HTTP 경계 + 인메모리 케이스 상태만.

실행: python scripts/train_baseline.py ; python mcp_http_gateway.py → http://localhost:8000
"""
from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agent.verification import Verifier
from agent.investigate import Investigator
from agent.verification_chat import VerificationChatAgent
from app_mcp import tools
from app_mcp.schemas import profile_from_dict, result_to_dict, transaction_from_dict
from contracts.verification_chat import VerificationTurnInput
from core.baseline import BaselineStore
from core.features import to_feature_vector
from core.pipeline import FraudGuardPipeline

MODEL_PATH = os.environ.get("FRAUDGUARD_MODEL", os.path.join(_ROOT, "data", "models", "baseline.joblib"))
META_PATH = os.path.join(_ROOT, "data", "models", "baseline_meta.json")
SYNTH = os.path.join(_ROOT, "data", "synth")
_WEB = os.path.join(_ROOT, "web")                      # 대시보드/콘솔 정적 자산 모음
DASHBOARD = os.path.join(_WEB, "dashboard_v2.html")    # 기본 콘솔 = 최신 v2(개발용)
DASHBOARD_V1 = os.path.join(_WEB, "dashboard.html")    # 구버전(제출본 미포함) → /v1
CUSTOMER_PAGE = os.path.join(_WEB, "customer_mobile.html")  # 고객 스마트폰 시뮬레이터
COUNSELOR_PAGE = os.path.join(_WEB, "counselor_workspace.html")  # 상담사 PC 워크스페이스
AGENTS_PAGE = os.path.join(_WEB, "agents_console.html")  # 실제 AI 에이전트(조사/본인확인) 콘솔
AUDIT_LOG = os.environ.get("FRAUDGUARD_AUDIT", os.path.join(_ROOT, "audit.jsonl"))

GRAPHS = {
    "dist_overview": os.path.join(SYNTH, "dist_overview.png"),
    "sensitivity_overview": os.path.join(SYNTH, "sensitivity_overview.png"),
    "learning_curve": os.path.join(SYNTH, "learning_curve.png"),
    "bootstrap_ci": os.path.join(SYNTH, "bootstrap_ci.png"),
    "eval_external": os.path.join(_ROOT, "data", "external", "eval_external.png"),
}
# 검증 그래프 네이티브 렌더용 JSON (스크립트가 PNG 옆에 덤프; 브라우저 Plotly 가 직접 그림)
VAL_JSON = {
    "sensitivity": os.path.join(SYNTH, "sensitivity_overview.json"),
    "learning_curve": os.path.join(SYNTH, "learning_curve.json"),
    "bootstrap_ci": os.path.join(SYNTH, "bootstrap_ci.json"),
    "eval_external": os.path.join(_ROOT, "data", "external", "eval_external.json"),
}
_TX_COLS = ["tx_id", "customer_id", "timestamp", "amount", "channel", "counterparty_country",
            "device_id", "ip_country", "balance_before", "balance_drawdown_ratio",
            "is_new_device", "tx_velocity_24h"]
_PROF_COLS = ["customer_id", "nationality", "visa_type", "residency_end_date", "language", "home_country"]


def _row_to_payload(row: dict) -> dict:
    tx = {k: row[k] for k in _TX_COLS if k in row}
    tx["timestamp"] = float(tx["timestamp"]); tx["amount"] = float(tx["amount"])
    tx["balance_before"] = float(tx.get("balance_before", 0))
    tx["balance_drawdown_ratio"] = float(tx["balance_drawdown_ratio"])
    tx["is_new_device"] = str(row.get("is_new_device", "0")) in ("1", "True", "true")
    tx["tx_velocity_24h"] = int(float(tx["tx_velocity_24h"]))
    prof = {k: row[k] for k in _PROF_COLS if k in row}
    return {"transaction": tx, "profile": prof}


def _read_csv(name):
    path = os.path.join(SYNTH, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _first(csv_name):
    rows = _read_csv(csv_name)
    return _row_to_payload(rows[0]) if rows else None


def _load_examples():
    out = []
    for ex_id, label, tool, csv_name in [
            ("normal", "정상 (VN E-9 일상결제)", "score_transaction", "normal_VN_E-9.csv"),
            ("takeover", "시나리오 A · 계좌양도", "detect_account_takeover", "anomaly_VN_E-9.csv"),
            ("phishing", "시나리오 B · 모국어 피싱", "request_verification", "anomaly_NP_D-2.csv")]:
        pl = _first(csv_name)
        if pl:
            out.append({"id": ex_id, "label": label, "tool": tool, **pl})
    return out


# --- 전역 상태 ---
META = json.load(open(META_PATH, encoding="utf-8")) if os.path.exists(META_PATH) else {}
REF_DATE = META.get("ref_date", date.today().isoformat())
_REF = date.fromisoformat(REF_DATE)
# P0-2: 라이브 API(PIPE)는 실제 today(date.today())로 채점한다 — ref_date 에 고정하면
#   실거래의 D-day(days_to_residency_end)가 통째로 어긋난다. 반면 _REPLAY 는 합성 큐를
#   '생성 당시 기준일(_REF)'로 재생하기 위한 데모 전용(재현성). 둘은 같은 모델 store 를 공유.
if os.path.exists(MODEL_PATH):
    _STORE = BaselineStore.load(MODEL_PATH)
    PIPE = FraudGuardPipeline(baseline=_STORE)              # 라이브: today=date.today()
    _REPLAY = FraudGuardPipeline(baseline=_STORE, today=_REF)  # 합성 큐 재생(데모 재현)
    MODEL_LOADED = True
else:
    PIPE = FraudGuardPipeline()
    _REPLAY = PIPE
    MODEL_LOADED = False
VERIFIER = Verifier(mode=os.environ.get("FRAUDGUARD_VERIFY_MODE", "template"))
INVESTIGATOR = Investigator(
    mode=os.environ.get("FRAUDGUARD_INVESTIGATE_MODE",
                        os.environ.get("FRAUDGUARD_VERIFY_MODE", "template")),
    model=os.environ.get("FRAUDGUARD_LLM_MODEL", "claude-sonnet-4-6"))
VERIFICATION_CHAT = VerificationChatAgent(
    mode=os.environ.get("FRAUDGUARD_CHAT_MODE",
                        os.environ.get("FRAUDGUARD_VERIFY_MODE", "template")),
    model=os.environ.get("FRAUDGUARD_LLM_MODEL", "claude-sonnet-4-6"))
EXAMPLES = _load_examples()

_STATUS = {  # 처리 결과 코드 → 한글
    "open": "대기", "verifying": "본인확인중", "escalated": "상신됨(분석가 대기)",
    "approved": "정상승인", "blocked": "차단확정", "holding": "보류유지", "reported": "STR보고",
}

# 시연 언어 강제(예: ko) — 조사관·대화 프롬프트 언어를 override 해 시연을 한국어로 이해 가능하게.
# 미설정이면 고객 실제 language(vi/ne). 실제 배포=고객 모국어, 시연=이해용 한국어(정직 병기).
DEMO_LANG = os.environ.get("FRAUDGUARD_DEMO_LANG")

# 실제 tool-calling/대화 에이전트(investigator_agent·verification_agent)용 모델.
# 이 두 경로는 실제 Claude API 를 호출한다(ANTHROPIC_API_KEY 필요) — 기존 단발
# INVESTIGATOR/VERIFIER(template 폴백)와 별개의 '진짜 에이전트' 엔드포인트.
AGENT_MODEL = os.environ.get("FRAUDGUARD_AGENT_MODEL", "claude-opus-4-8")


def _apply_demo_lang(alert_copy: dict) -> dict:
    if DEMO_LANG:
        alert_copy["language"] = DEMO_LANG
    return alert_copy


def _audit(event: dict) -> None:
    event["logged_at"] = time.time()
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _parse_query(path: str) -> dict:
    """URL 쿼리스트링 안전 파싱 — '=' 없는 토큰은 무시(ValueError 크래시 방지, P2-6)."""
    if "?" not in path:
        return {}
    out = {}
    for tok in path.split("?", 1)[1].split("&"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[unquote(k)] = unquote(v)  # %3A 등 URL 디코드(예: seg=VN%3AE-9 → VN:E-9)
    return out


def _qint(q: dict, key: str, default: int) -> int:
    """쿼리값 안전 정수화 — 잘못된 값이면 기본값(크래시 가드)."""
    try:
        return int(q.get(key, default))
    except (TypeError, ValueError):
        return default


def _severity(rule_score, model_pctl, p):
    """축-공정 심각도(0~1): 각 축이 '자기 review 임계를 넘어 천장(1.0)까지' 간 정도의 max.

    ⑤ risk_score=max(룰 페널티공간, 모델 분위공간)은 스케일이 달라(룰발 soft_block≈0.6 <
    모델발 0.99) 절대비교가 왜곡된다 → 그대로 priority 에 쓰면 룰발 적중이 부당하게 밀린다.
    여기서 각 축을 '자기 임계 기준'으로 정규화해 공정 비교한다. 단 축 간 심각도의 절대
    동치는 라벨 없이는 불가 — 휴리스틱임을 명시(정직성). 결정 자체는 이미 action 으로 끝났다.
    """
    def _norm(v, lo):
        return max(0.0, (v - lo) / (1.0 - lo)) if (v is not None and v > lo) else 0.0
    return max(_norm(rule_score, p.rule_review_score), _norm(model_pctl, p.review_q))


def _build_alerts():
    """합성 거래를 채점해 '검토/보류' 알림 큐 구성(진짜 이상치 + 분위수 오탐 혼합)."""
    import numpy as np
    rng = np.random.default_rng(7)
    all_rows = _read_csv("synth_all.csv")
    if not all_rows:  # 폴백: 분리 파일
        all_rows = (_read_csv("anomaly_VN_E-9.csv") + _read_csv("anomaly_NP_D-2.csv")
                    + _read_csv("normal_VN_E-9.csv")[:120] + _read_csv("normal_NP_D-2.csv")[:120])
    flagged = []
    # P0-3: '오탐(정상→검토)' 후보는 학습에 안 쓴 held-out(synth_eval.csv)에서 뽑는다.
    #   synth_all 의 정상은 train_baseline 학습데이터라 in-sample 분위(낙관적 누수)가 된다.
    eval_rows = _read_csv("synth_eval.csv")
    label0 = [r for r in eval_rows if str(r.get("label")) == "0"]
    if not label0:  # 폴백(eval 분할 미생성 구버전): in-sample — gen_synth 재실행 권장
        label0 = [r for r in all_rows if str(r.get("label")) == "0"]
    # P2-10: 이상치 후보 = held-out 혼합난이도(borderline 포함) + 극단(obvious) — 전부 s=1 방지.
    label1_mixed = [r for r in eval_rows if str(r.get("label")) == "1"]
    label1_extreme = [r for r in all_rows if str(r.get("label")) == "1"]
    rng.shuffle(label1_mixed); rng.shuffle(label1_extreme); rng.shuffle(label0)
    label1 = label1_mixed[:80] + label1_extreme[:40]
    rng.shuffle(label1)
    pool = label1[:90] + label0[:600]
    for row in pool:
        pl = _row_to_payload(row)
        tx = transaction_from_dict(pl["transaction"])
        prof = profile_from_dict(pl["profile"])
        res = _REPLAY.detect_account_takeover(tx, prof)  # 합성 큐 재생(ref_date 기준). 비임박이면 score 와 동일
        if res.action == "allow":
            continue
        x = to_feature_vector(tx, prof, today=_REF)
        if _REPLAY.baseline.has(prof.segment_key):
            feats, exp_method = _REPLAY.explainer.explain_faithful(_REPLAY.baseline, prof.segment_key, x)
        else:
            feats, exp_method = {}, "none"
        axes = res.explanation.get("axes", {})
        flagged.append({
            "created_at": None,  # 아래서 부여
            "status": "open", "decision": None, "verification": None, "activity": [],
            "customer_id": prof.customer_id, "segment": prof.segment_key,
            "nationality": prof.nationality, "visa_type": prof.visa_type, "language": prof.language,
            "days_to_residency_end": int(x[6]),  # P2-6: 위에서 만든 x 재사용(2회 호출 제거)
            "amount": tx.amount, "channel": tx.channel, "counterparty_country": tx.counterparty_country,
            "ip_country": tx.ip_country, "is_new_device": bool(tx.is_new_device),
            "tx_velocity_24h": tx.tx_velocity_24h, "balance_drawdown_ratio": tx.balance_drawdown_ratio,
            "action": res.action, "risk_score": res.risk_score, "rule_score": res.rule_score,
            "model_pctl": axes.get("model_pctl"), "rule_action": axes.get("rule_action"),
            "model_action": axes.get("model_action"),
            "triggered_rules": res.triggered_rules,
            "takeover_boost": res.explanation.get("takeover_boost"),
            "explanation": feats, "explain_method": exp_method,
        })
    # 트리아지 현실성: 차단보류(진짜 이상) + 검토(분위수 오탐)을 섞는다
    soft = [a for a in flagged if a["action"] == "soft_block"]
    rev = [a for a in flagged if a["action"] == "review"]
    rng.shuffle(soft); rng.shuffle(rev)
    flagged = soft[:30] + rev[:20]
    # created_at: 오늘 업무시간(KST)에 분산, 최신 정렬. hour 피처와 동일하게 로컬시각(KST) 규약.
    base = datetime(_REF.year, _REF.month, _REF.day, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    offs = sorted(rng.integers(0, 9 * 3600, size=len(flagged)).tolist())
    p = PIPE.decision.p  # 임계(rule_review_score / review_q) — 축-공정 심각도 정규화에 사용
    alerts = {}
    for i, (a, off) in enumerate(zip(sorted(flagged, key=lambda a: a["risk_score"]), offs), 1):
        a["id"] = f"FG-{REF_DATE.replace('-', '')}-{i:04d}"
        a["created_at"] = (base + timedelta(seconds=int(off))).isoformat()
        # ⑤ 트리아지 우선순위(콘솔 표시 휴리스틱, core 결정 임계 아님):
        #   액션 레벨이 1차 → 축-공정 심각도(스케일 왜곡 제거) → 양축 합치(신뢰↑) → 임박/신규기기.
        both_axes = a["rule_action"] != "allow" and a["model_action"] != "allow"
        a["priority"] = round((100 if a["action"] == "soft_block" else 50)   # 액션 레벨 = 1차 정렬
                              + _severity(a["rule_score"], a["model_pctl"], p) * 12  # 축-공정 심각도
                              + (15 if both_axes else 0)                      # 룰·모델 동시 발화 = 코로보레이션
                              + max(0, 30 - a["days_to_residency_end"]) * 0.8  # 출국 임박 가중
                              + (5 if a["is_new_device"] else 0), 1)
        alerts[a["id"]] = a
    return alerts


def _build_distributions(bins: int = 40):
    """'분포' 탭용 정적 데이터(스트리밍 아님 — 한 번 계산해 통째로 제공).

    그룹별로 ① 학습 정상 점수분포(scores_sorted) ② held-out 정상/사기 점수분포(synth_eval 채점)
    를 같은 bin 으로 히스토그램화 + ECDF-일관 임계 + 실측 FPR/꼬리적중 요약.
    모델은 고정(로드만, 불변원칙 4) — 채점만. in-sample 누수 방지로 held-out 사용(P0-3)."""
    import numpy as np
    eval_rows = _read_csv("synth_eval.csv")
    ev_by_seg: dict[str, dict] = {}
    for row in eval_rows:
        seg = f"{row.get('nationality')}:{row.get('visa_type')}"
        if not _STORE.has(seg):
            continue
        pl = _row_to_payload(row)
        tx = transaction_from_dict(pl["transaction"])
        prof = profile_from_dict(pl["profile"])
        x = to_feature_vector(tx, prof, today=_REF)
        score = float(_STORE.anomaly_score(seg, x))
        pctl = float(_STORE.percentile_of_scores(seg, [score])[0])
        d = ev_by_seg.setdefault(seg, {"normal": [], "fraud": []})
        d["fraud" if int(float(row.get("label", 0))) == 1 else "normal"].append((score, pctl))
    p = PIPE.decision.p
    out = {}
    for seg in _STORE._models:
        ss = np.asarray(_STORE.artifacts(seg)["scores_sorted"], dtype=float)
        n = len(ss)
        ev = ev_by_seg.get(seg, {"normal": [], "fraud": []})
        evn = [s for s, _ in ev["normal"]]
        evf = [s for s, _ in ev["fraud"]]
        allv = np.concatenate([ss, np.asarray(evn or [ss.min()]), np.asarray(evf or [ss.min()])])
        edges = np.histogram_bin_edges(allv, bins=max(5, min(bins, 100)))

        def _h(v):
            return [int(c) for c in np.histogram(np.asarray(v, dtype=float), bins=edges)[0]] if len(v) else [0] * (len(edges) - 1)

        def _score_at(q):
            return float(ss[min(int(np.ceil(q * n)) - 1, n - 1)])
        sb_q = p.soft_block_q
        evn_tail = sum(1 for _, pc in ev["normal"] if pc >= sb_q)
        evf_tail = sum(1 for _, pc in ev["fraud"] if pc >= sb_q)
        out[seg] = {
            "segment": seg, "n_train": int(n),
            "hist": {"edges": [round(float(e), 4) for e in edges],
                     "train_normal": _h(ss), "eval_normal": _h(evn), "eval_fraud": _h(evf)},
            "thresholds": {"review_q": p.review_q, "soft_block_q": sb_q,
                           "review_score": round(_score_at(p.review_q), 4),
                           "soft_block_score": round(_score_at(sb_q), 4)},
            "summary": {"eval_normal_n": len(evn), "eval_normal_tail": evn_tail,
                        "fpr": round(evn_tail / max(len(evn), 1), 4), "fpr_target": round(1 - sb_q, 4),
                        "eval_fraud_n": len(evf), "eval_fraud_tail": evf_tail,
                        "tail_catch": round(evf_tail / max(len(evf), 1), 4)},
        }
    return out


def _build_synth_dist(bins: int = 36) -> dict:
    """dist_overview 네이티브용 — 합성 거래 주요 피처 분포(정상 vs 이상)를 synth_all.csv 에서 계산.
    gen_synth 재실행 없이 기존 CSV 로부터(분포 차용이 의도대로인지 시각 검증; 모델 무관)."""
    import numpy as np
    rows = _read_csv("synth_all.csv")
    if not rows:
        return {}

    def split(name, transform=lambda v: v):
        a0, a1 = [], []
        for r in rows:
            raw = r.get(name)
            if raw in (None, ""):
                continue
            try:
                v = transform(float(raw))
            except (ValueError, TypeError):
                continue
            if v is None:
                continue
            (a1 if str(r.get("label")) == "1" else a0).append(v)
        return np.asarray(a0, float), np.asarray(a1, float)

    def panel(key, title, a0, a1, lo=None, hi=None):
        allv = np.concatenate([a0, a1]) if (len(a0) + len(a1)) else np.array([0.0, 1.0])
        lo = float(np.min(allv)) if lo is None else lo
        hi = float(np.max(allv)) if hi is None else hi
        if hi <= lo:
            hi = lo + 1.0
        edges = np.linspace(lo, hi, bins + 1)
        return {"key": key, "title": title, "edges": [round(float(e), 4) for e in edges],
                "normal": [int(c) for c in np.histogram(a0, bins=edges)[0]],
                "anomaly": [int(c) for c in np.histogram(a1, bins=edges)[0]]}

    amt0, amt1 = split("amount", lambda v: np.log10(v) if v > 0 else None)
    dd0, dd1 = split("balance_drawdown_ratio")
    v0, v1 = split("tx_velocity_24h")
    vmax = float(max(v0.max() if len(v0) else 1, v1.max() if len(v1) else 1, 1))
    isnew = lambda r: str(r.get("is_new_device")) in ("1", "True", "true")
    n0 = sum(1 for r in rows if str(r.get("label")) != "1") or 1
    n1 = sum(1 for r in rows if str(r.get("label")) == "1") or 1
    nd0 = sum(1 for r in rows if str(r.get("label")) != "1" and isnew(r))
    nd1 = sum(1 for r in rows if str(r.get("label")) == "1" and isnew(r))
    return {
        "panels": [panel("amount", "송금액 log10 (로그정규)", amt0, amt1),
                   panel("drawdown", "잔액 인출률 (베타)", dd0, dd1, 0.0, 1.0),
                   panel("velocity", "24h 거래수 (포아송)", v0, v1, 0.0, vmax)],
        "new_device": {"normal": round(nd0 / n0, 4), "anomaly": round(nd1 / n1, 4)},
    }


ALERTS = _build_alerts() if MODEL_LOADED else {}
_DIST = _build_distributions() if MODEL_LOADED else {}
_SYNTH_DIST = _build_synth_dist()  # CSV 기반(모델 무관)
_ALERTS_LOCK = threading.Lock()  # P2-3: ThreadingHTTPServer 동시요청의 ALERTS RMW 직렬화


def _alert_summary(a):
    return {k: a[k] for k in ("id", "created_at", "status", "customer_id", "segment",
                              "days_to_residency_end", "amount", "channel", "counterparty_country",
                              "action", "risk_score", "triggered_rules", "priority", "is_new_device")}


def _kpi():
    with _ALERTS_LOCK:
        vals = list(ALERTS.values())
    # P2-6: 'holding'(보류유지)도 미결 큐로 집계 — 안 그러면 어떤 KPI/필터에도 안 잡혀 림보.
    openq = [a for a in vals if a["status"] in ("open", "verifying", "holding", "escalated")]
    by_group = {}
    for a in openq:
        by_group.setdefault(a["segment"], 0)
        by_group[a["segment"]] += 1
    resolved = [a for a in vals if a["status"] in ("approved", "blocked", "reported")]
    return {
        "open_total": len(openq),
        "soft_block": len([a for a in openq if a["action"] == "soft_block"]),
        "review": len([a for a in openq if a["action"] == "review"]),
        "verifying": len([a for a in openq if a["status"] == "verifying"]),
        "holding": len([a for a in openq if a["status"] == "holding"]),
        "resolved": len(resolved),
        # P0-필터정합: 사이드바 승인/차단/STR 배지가 같은 합계를 쓰지 않도록 상태별 분리.
        "approved": len([a for a in resolved if a["status"] == "approved"]),
        "blocked": len([a for a in resolved if a["status"] == "blocked"]),
        "reported": len([a for a in resolved if a["status"] == "reported"]),
        "imminent": len([a for a in openq if a["days_to_residency_end"] < 10]),
        "avg_risk": round(sum(a["risk_score"] for a in openq) / max(len(openq), 1), 3),
        "by_group": by_group,
        # P1-1: group_recall_gap 은 라벨 없이 라이브 계산 불가(형평성=오프라인 bootstrap_ci 측정).
        #   합성·임의난이도에서 잰 상수를 운영 KPI 로 노출하면 '정직성' 명제에 반하므로 제거.
        #   그룹 Recall 격차는 scripts/bootstrap_ci.py 그래프(오프라인)에서만 보고한다.
        "fpr_target": round(1 - PIPE.decision.p.soft_block_q, 4),
    }


_DISPATCH = {
    "score_transaction": lambda b: tools.score_transaction(PIPE, b["transaction"], b["profile"]),
    "detect_account_takeover": lambda b: tools.detect_account_takeover(PIPE, b["transaction"], b["profile"]),
    "request_verification": lambda b: tools.request_verification(PIPE, VERIFIER, b["transaction"], b["profile"]),
    "register_baseline": lambda b: tools.register_baseline(PIPE, b["segment_key"], b["samples"]),
}

_DECISION_STATUS = {"approve": "approved", "block": "blocked", "hold": "holding",
                    "verify": "verifying", "escalate": "escalated", "sar": "reported"}

# 직무분리(전자금융감독규정: 고위험 거래 복수인력/일선·후선 분리). 상담사는 본인확인·상신만,
# 결정(승인/차단/보류)은 분석가. role 미지정(None)=하위호환으로 제한 없음(기존 콘솔/테스트).
_ROLE_ACTIONS = {
    "agent": {"verify", "escalate"},                    # 상담사(콜센터): 본인확인 발송·상신, 결정 불가
    "analyst": {"approve", "block", "hold", "verify"},  # 분석가(FDS): 승인/차단/보류 + verify 요청
}


def _decide(alert_id, body):
    dec = body.get("decision")
    if dec not in _DECISION_STATUS:
        return {"error": f"unknown decision '{dec}'"}, 400
    # 직무분리 강제: role 지정 시 해당 역할이 못 하는 결정은 거부(알림 조회 전에 차단).
    role = body.get("role")  # "agent"(상담사) | "analyst"(분석가) | None(하위호환)
    if role is not None and dec not in _ROLE_ACTIONS.get(role, set()):
        return {"error": f"role '{role}' cannot perform '{dec}'",
                "allowed": sorted(_ROLE_ACTIONS.get(role, []))}, 403
    now = datetime.now(timezone.utc).isoformat()
    # P2-3: 조회→수정→기록을 락으로 묶어 동시요청 레이스 방지. 끝에 스냅샷 사본을 반환.
    with _ALERTS_LOCK:
        a = ALERTS.get(alert_id)
        if a is None:
            return {"error": "alert not found"}, 404
        a["status"] = _DECISION_STATUS[dec]
        a["decision"] = {"decision": dec, "role": role, "note": body.get("note", ""), "at": now}
        if dec == "verify":  # 모국어 본인확인 발송
            from core.schema import CustomerProfile, Transaction
            prof = CustomerProfile(a["customer_id"], a["nationality"], a["visa_type"],
                                   _REF + timedelta(days=a["days_to_residency_end"]), a["language"], a["nationality"])
            tx = Transaction(a["id"], a["customer_id"], 0.0, a["amount"], a["channel"],
                             a["counterparty_country"], "-", a["ip_country"], 0.0,
                             a["balance_drawdown_ratio"], a["is_new_device"], a["tx_velocity_24h"])
            a["verification"] = VERIFIER.request(tx, prof)
        # 정보공유/인계: 역할 태그가 있는 처리만 append-only activity 로 남긴다.
        # role 미지정 호출은 구버전 콘솔/API 하위호환 경로라 decision/audit 만 유지한다.
        if role is not None or body.get("operator_id") is not None:
            a.setdefault("activity", []).append({
                "role": role or "unspecified", "action": dec, "note": body.get("note", ""),
                "operator_id": body.get("operator_id"), "at": now})
        snapshot = dict(a)
    _audit({"tool": "alert_decision", "alert_id": alert_id, "decision": dec, "role": role,
            "status": snapshot["status"], "note": body.get("note", "")})
    return snapshot, 200


def _verification_case_from_alert(a: dict) -> dict:
    """알림 dict → 기존 1회성 모국어 본인확인 케이스. core 는 모르는 HTTP 상태 보조."""
    from core.schema import CustomerProfile, Transaction

    prof = CustomerProfile(a["customer_id"], a["nationality"], a["visa_type"],
                           _REF + timedelta(days=a["days_to_residency_end"]), a["language"], a["nationality"])
    tx = Transaction(a["id"], a["customer_id"], 0.0, a["amount"], a["channel"],
                     a["counterparty_country"], "-", a["ip_country"], 0.0,
                     a["balance_drawdown_ratio"], a["is_new_device"], a["tx_velocity_24h"])
    return VERIFIER.request(tx, prof)


def _reply_status(next_state: str) -> str:
    """대화 결과는 최종 승인/차단이 아니라 큐 상태만 보수적으로 이동시킨다."""
    if next_state == "release_candidate":
        return "verifying"      # 분석가가 최종 정상승인을 눌러야 완료.
    return "holding"            # 위험/불명확 답변은 보류 유지.


def _verification_reply(alert_id: str, body: dict):
    """고객 답변 1턴 처리 → intent/요약/라우팅 후보 저장."""
    try:
        turn_input = VerificationTurnInput(**body)
    except Exception as e:
        return {"error": f"bad verification reply: {type(e).__name__}: {e}"}, 400

    with _ALERTS_LOCK:
        a = ALERTS.get(alert_id)
        if a is None:
            return {"error": "alert not found"}, 404
        alert_copy = _apply_demo_lang(dict(a))
        existing_turns = list(a.get("verification_turns") or [])
        turn_index = len(existing_turns) + 1

    # 모국어 발송 없이 답변 API 가 먼저 호출된 경우에도 데모/오케스트레이터가 이어갈 수 있게
    # 발송 케이스를 한 번 생성한다. 외부 발송은 여전히 mock 이며 status dict 만 저장한다.
    verification = alert_copy.get("verification")
    if not verification:
        verification = _verification_case_from_alert(alert_copy)
        alert_copy["verification"] = verification

    result = VERIFICATION_CHAT.process(alert_copy, turn_input, turn_index=turn_index)
    with _ALERTS_LOCK:
        cur = ALERTS.get(alert_id)
        if cur is not None:
            if not cur.get("verification"):
                cur["verification"] = verification
            turns = cur.setdefault("verification_turns", [])
            turns.append(result)
            cur["verification_result"] = result
            cur["status"] = _reply_status(result["next_state"])
            cur["decision"] = {
                "decision": "verification_reply",
                "note": result["next_state"],
                "at": datetime.now(timezone.utc).isoformat(),
            }
    _audit({"tool": "alert_verification_reply", "alert_id": alert_id,
            "intent": result.get("detected_intent"), "next_state": result.get("next_state"),
            "generated_by": result.get("generated_by")})
    return result, 200


def _investigate(alert_id):
    """알림 1건을 근거 기반 조사관 리포트로 요약하고 케이스에 저장."""
    with _ALERTS_LOCK:
        a = ALERTS.get(alert_id)
        if a is None:
            return {"error": "alert not found"}, 404
        alert_copy = _apply_demo_lang(dict(a))
    # LLM/캐시/repair 는 락 밖에서 수행한다 — claude/openai 모드면 네트워크 호출이 발생하므로
    # 락을 점유한 채 대기하면 /alerts·/decision·KPI 등 다른 요청이 함께 막힌다.
    report = INVESTIGATOR.request_from_alert(alert_copy)
    with _ALERTS_LOCK:
        cur = ALERTS.get(alert_id)
        if cur is not None:
            cur["investigation"] = report
    _audit({"tool": "alert_investigate", "alert_id": alert_id,
            "generated_by": report.get("generated_by"),
            "suspected_type": report.get("suspected_type")})
    return report, 200


def _agent_investigate(alert_id):
    """진짜 tool-calling 조사 에이전트(investigator_agent)를 알림 1건에 실행.

    기존 _investigate(단발 LLM)와 별개 — Claude 가 read-only 도구를 스스로 호출하며
    근거를 모으고 확인질문·가설을 제출한다. 실제 API 호출(락 밖)."""
    with _ALERTS_LOCK:
        a = ALERTS.get(alert_id)
        if a is None:
            return {"error": "alert not found"}, 404
        alert_copy = _apply_demo_lang(dict(a))
    try:
        from investigator_agent import InvestigatorAgent, ToolContext
        ctx = ToolContext.from_alert(alert_copy)
        out = InvestigatorAgent(model=AGENT_MODEL).investigate(ctx)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}",
                "hint": "실제 Claude API 필요 — anthropic 설치 + ANTHROPIC_API_KEY 설정"}, 502
    payload = {"tx_id": out.tx_id, "turns": out.turns, "stop_reason": out.stop_reason,
               "model": out.model, "tool_calls": out.tool_calls, "submitted": out.submitted}
    with _ALERTS_LOCK:
        cur = ALERTS.get(alert_id)
        if cur is not None:
            cur["agent_investigation"] = payload
    _audit({"tool": "agent_investigate", "alert_id": alert_id, "model": out.model,
            "turns": out.turns, "tools": len(out.tool_calls)})
    return payload, 200


def _agent_verify(alert_id, body):
    """진짜 다회전 모국어 대화 에이전트(verification_agent)를 알림 1건에 실행(시뮬 고객).

    고객 자리엔 데모용 시뮬레이터(원격제어 피싱 피해자)를 넣는다 — 실제 발송/채널은
    여전히 미연동(정직). 에이전트가 강요/원격제어를 탐지하면 보호상신 후보를 만든다.
    판정(승인/차단)은 사람 몫 — 큐 상태는 _reply_status 로 보수적으로만 이동."""
    with _ALERTS_LOCK:
        a = ALERTS.get(alert_id)
        if a is None:
            return {"error": "alert not found"}, 404
        alert_copy = _apply_demo_lang(dict(a))
    try:
        from verification_agent import VerificationAgent, VerificationCase, LlmCustomer
        case = VerificationCase.from_alert(alert_copy)
        customer = LlmCustomer(language=case.language)  # 시뮬 고객(실제 고객 아님)
        dlg = VerificationAgent(model=AGENT_MODEL).converse(case, customer)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}",
                "hint": "실제 Claude API 필요 — anthropic 설치 + ANTHROPIC_API_KEY 설정"}, 502
    payload = {"tx_id": dlg.tx_id, "customer_turns": dlg.customer_turns,
               "stop_reason": dlg.stop_reason, "model": dlg.model,
               "simulated_customer": True, "transcript": dlg.transcript,
               "conclusion": dlg.conclusion}
    with _ALERTS_LOCK:
        cur = ALERTS.get(alert_id)
        if cur is not None:
            cur["agent_verification"] = payload
            if dlg.conclusion:
                cur["status"] = _reply_status(dlg.conclusion.get("next_state", ""))
                cur["decision"] = {"decision": "agent_verification",
                                   "note": dlg.conclusion.get("next_state"),
                                   "at": datetime.now(timezone.utc).isoformat()}
    _audit({"tool": "agent_verify", "alert_id": alert_id, "model": dlg.model,
            "intent": (dlg.conclusion or {}).get("detected_intent"),
            "next_state": (dlg.conclusion or {}).get("next_state")})
    return payload, 200


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, ctype, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self._send(204, "text/plain", b"")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/v2", "/v2.html"):
            if os.path.exists(DASHBOARD):
                self._send(200, "text/html; charset=utf-8", open(DASHBOARD, "rb").read())
            else:
                self._json({"error": "dashboard_v2.html 없음"}, 404)
        elif path.startswith("/customer/"):
            if os.path.exists(CUSTOMER_PAGE):
                self._send(200, "text/html; charset=utf-8", open(CUSTOMER_PAGE, "rb").read())
            else:
                self._json({"error": "customer_mobile.html 없음"}, 404)
        elif path in ("/agents", "/agents.html"):
            if os.path.exists(AGENTS_PAGE):
                self._send(200, "text/html; charset=utf-8", open(AGENTS_PAGE, "rb").read())
            else:
                self._json({"error": "agents_console.html 없음"}, 404)
        elif path.startswith("/counselor/"):
            if os.path.exists(COUNSELOR_PAGE):
                self._send(200, "text/html; charset=utf-8", open(COUNSELOR_PAGE, "rb").read())
            else:
                self._json({"error": "counselor_workspace.html 없음"}, 404)
        elif path in ("/v1", "/v1.html"):
            if os.path.exists(DASHBOARD_V1):
                self._send(200, "text/html; charset=utf-8", open(DASHBOARD_V1, "rb").read())
            else:
                self._json({"error": "dashboard.html 없음"}, 404)
        elif path == "/jb_logo.png":
            logo_path = os.path.join(_WEB, "jb_logo.png")
            if os.path.exists(logo_path):
                self._send(200, "image/png", open(logo_path, "rb").read())
            else:
                self._json({"error": "jb_logo.png 없음"}, 404)
        elif path == "/health":
            self._json({"ok": True, "ref_date": REF_DATE, "model_loaded": MODEL_LOADED,
                        "segments": list(META.get("segments", {}).keys()),
                        "verify_mode": VERIFIER.mode, "alerts": len(ALERTS),
                        "chat_mode": VERIFICATION_CHAT.mode,
                        "review_q": PIPE.decision.p.review_q, "soft_block_q": PIPE.decision.p.soft_block_q})
        elif path == "/kpi":
            self._json(_kpi())
        elif path == "/alerts":
            q = _parse_query(self.path)  # P2-6: '=' 없는 쿼리도 안전 파싱(크래시 가드)
            with _ALERTS_LOCK:
                items = [_alert_summary(a) for a in ALERTS.values()
                         if (q.get("status") in (None, "all") or a["status"] == q.get("status"))]
            items.sort(key=lambda a: a["created_at"] or "", reverse=True)
            self._json(items)
        elif path.startswith("/alert/"):
            a = ALERTS.get(path[len("/alert/"):])
            self._json(a if a else {"error": "not found"}, 200 if a else 404)
        elif path == "/examples":
            self._json(EXAMPLES)
        elif path == "/thresholds":
            self._json(META.get("segments", {}))
        elif path == "/stats/segments":
            self._json(list(_DIST.keys()) if MODEL_LOADED else [])
        elif path == "/stats/distribution":
            seg = _parse_query(self.path).get("seg")
            d = _DIST.get(seg) if MODEL_LOADED else None
            self._json(d if d else {"error": "unknown segment"}, 200 if d else 404)
        elif path == "/stats/synth_dist":
            self._json(_SYNTH_DIST or {"error": "synth_all.csv 없음"}, 200 if _SYNTH_DIST else 404)
        elif path.startswith("/stats/validation/"):
            fp = VAL_JSON.get(path[len("/stats/validation/"):])
            if fp and os.path.exists(fp):
                self._send(200, "application/json; charset=utf-8", open(fp, "rb").read())
            else:
                self._json({"error": "validation json 없음 (해당 스크립트 먼저 실행)"}, 404)
        elif path.startswith("/graph/"):
            fp = GRAPHS.get(path[len("/graph/"):])
            if fp and os.path.exists(fp):
                self._send(200, "image/png", open(fp, "rb").read())
            else:
                self._json({"error": "graph 없음(스크립트 먼저 실행)"}, 404)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json({"error": f"bad body: {e}"}, 400)
        if path.startswith("/alert/") and path.endswith("/decision"):
            aid = path[len("/alert/"):-len("/decision")]
            obj, st = _decide(aid, body)
            return self._json(obj, st)
        if path.startswith("/alert/") and path.endswith("/verification/reply"):
            aid = path[len("/alert/"):-len("/verification/reply")]
            obj, st = _verification_reply(aid, body)
            return self._json(obj, st)
        # 주의: '/agent/investigate' 도 '/investigate' 로 끝나므로 더 구체적인 경로를 먼저 검사.
        if path.startswith("/alert/") and path.endswith("/agent/investigate"):
            aid = path[len("/alert/"):-len("/agent/investigate")]
            obj, st = _agent_investigate(aid)
            return self._json(obj, st)
        if path.startswith("/alert/") and path.endswith("/agent/verify"):
            aid = path[len("/alert/"):-len("/agent/verify")]
            obj, st = _agent_verify(aid, body)
            return self._json(obj, st)
        if path.startswith("/alert/") and path.endswith("/investigate"):
            aid = path[len("/alert/"):-len("/investigate")]
            obj, st = _investigate(aid)
            return self._json(obj, st)
        if path.startswith("/api/"):
            fn = _DISPATCH.get(path[len("/api/"):])
            if fn is None:
                return self._json({"error": "unknown tool"}, 404)
            try:
                return self._json(fn(body))
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 400)
        self._json({"error": "not found"}, 404)


def main():
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fraud-guard 콘솔(v2) → http://localhost:{port}  (구버전 /v1)  "
          f"(model={MODEL_LOADED}, alerts={len(ALERTS)}, ref_date={REF_DATE}, verify={VERIFIER.mode})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
