"""사기탐지 관제 API. 기업 관점 콘솔(8002)과 고객 폰(web)이 함께 쓴다.

역할 분담(중요):
- 판정 제안은 엔진(mcp_servers/fraud_guard/engine)이 계산한다.
- 고객 답변 의도분류도 엔진이 한다(안전신호 결정론 우선).
- 최종 결정(승인/차단/보류유지/재질문)은 사람 분석가가 콘솔 버튼으로 한다.
  AI 는 결정을 실행하지 않는다. 이 모듈은 분석가 결정을 기록만 한다.

상태는 데모용 인메모리 1벌이다(단일 프로세스 시연 전제). 서버 재시작이 곧 초기화다.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.personas import get_persona
from mcp_servers.fraud_guard import data as fdata
from mcp_servers.fraud_guard import _engine

router = APIRouter(prefix="/fraud", tags=["fraud"])

# 데모 케이스 상태(페르소나별 1건). 콘솔 폴링과 폰 답변이 이 상태를 공유한다.
_CASES: dict = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _subject(sid: str) -> dict:
    """대기열 대상자 정보 통합 조회. 페르소나(minh, suman)와 가상 대상자를 같은 형태로 준다.

    반환: {id, name, country, visa, flag, profile(엔진 입력), items(라벨+tx 리스트),
          seed_decision(초기 시드 결정 또는 None)}
    """
    if sid in fdata.EXTRA_SUSPECTS:
        s = fdata.extra_suspect(sid)
        return {
            "id": sid,
            "name": s["name"],
            "country": s["country"],
            "visa": s["visa"],
            "flag": s["flag"],
            "profile": fdata.suspect_profile(sid),
            "items": [s["item"]],
            "seed_decision": s.get("seed_decision"),
        }
    p = get_persona(sid)
    return {
        "id": sid,
        "name": p["name"],
        "country": p["country"],
        "visa": p["visa"],
        "flag": p.get("flag", ""),
        "profile": fdata.persona_to_profile(p),
        "items": fdata.demo_feed(sid),
        "seed_decision": None,
    }


def _score_feed(persona_id: str) -> dict:
    """피드 전 건을 엔진으로 채점해 콘솔 표시용 dict 로 만든다."""
    sub = _subject(persona_id)
    profile = sub["profile"]
    seg = f"{profile['nationality']}:{profile['visa_type']}"
    feed_out = []
    hero = None
    for i, item in enumerate(sub["items"]):
        # 대표(첫) 건은 계좌양도 가중까지, 나머지는 일반 채점
        r = _engine.takeover(profile, item["tx"]) if i == 0 else _engine.score(profile, item["tx"])
        axes = (r.get("explanation") or {}).get("axes", {})
        # 표시용 위험점수. 엔진 risk_score 는 정상분포 분위라 정상 거래도 90 이상이 나온다.
        # 화면 직관성을 위해 정상(allow)은 룰 점수 기준(대개 0)으로 낮게 표시한다.
        # 판정(action)은 어디까지나 엔진 값 그대로다.
        risk = r.get("risk_score") or 0
        display = round((r.get("rule_score") or 0) * 100) if r.get("action") == "allow" else round(risk * 100)
        row = {
            "tx_id": r["tx_id"],
            "label": item["label"],
            "amount_krw": item["tx"]["amount"],
            "channel": item["tx"]["channel"],
            "counterparty_country": item["tx"]["counterparty_country"],
            "is_new_device": item["tx"]["is_new_device"],
            "drawdown": item["tx"]["balance_drawdown_ratio"],
            "score": display,
            "action": r.get("action"),
            "action_ko": fdata.ACTION_LABELS_KO.get(r.get("action"), r.get("action")),
            "rule_score": r.get("rule_score"),
            "model_score": r.get("model_score"),
            "rule_action": axes.get("rule_action"),
            "model_action": axes.get("model_action"),
            "triggered_rules": list(r.get("triggered_rules") or []),
            "rules_ko": [fdata.RULE_LABELS_KO.get(x, x) for x in (r.get("triggered_rules") or [])],
            "xai": {
                fdata.FEATURE_LABELS_KO.get(k, k): v
                for k, v in _engine.explanation_features(r).items()
            },
        }
        feed_out.append(row)
        if i == 0:
            hero = row
    return {
        "persona": {"id": sub["id"], "name": sub["name"], "country": sub["country"], "visa": sub["visa"]},
        "segment": seg,
        "baseline": _engine.baseline_thresholds(seg),
        "feed": feed_out,
        "hero": hero,
    }


def _init_case(persona_id: str) -> dict:
    """대표 의심 거래의 케이스를 만들고 모국어 본인확인을 발송 상태로 둔다.

    가상 대상자에 seed_decision 이 있으면 이미 분석가가 처리를 마친 케이스로 시드한다
    (대기열에 처리 완료 건이 섞여 있어야 실제 관제 화면답다).
    """
    sub = _subject(persona_id)
    profile = sub["profile"]
    if not sub["items"]:
        raise HTTPException(404, f"{persona_id} 데모 거래 없음")
    item = sub["items"][0]
    r = _engine.takeover(profile, item["tx"])
    ver = _engine.verify(profile, item["tx"])
    inv = _engine.investigate(profile, item["tx"])
    # 콘솔 표시용 한국어 라벨을 브리핑에 부착(코드값은 그대로 둔다)
    inv["suspected_type_ko"] = fdata.SUSPECTED_LABELS_KO.get(
        inv.get("suspected_type"), inv.get("suspected_type"))
    inv["recommended_ko"] = fdata.RECOMMEND_LABELS_KO.get(
        inv.get("recommended_next_action"), inv.get("recommended_next_action"))
    inv["confidence_ko"] = fdata.CONFIDENCE_LABELS_KO.get(
        inv.get("confidence"), inv.get("confidence"))
    seed = sub["seed_decision"]
    return {
        "persona_id": persona_id,
        "tx_id": item["tx"]["tx_id"],
        "amount_krw": item["tx"]["amount"],
        "language": ver.get("language"),
        "status": "decided" if seed else "verifying",  # verifying -> replied -> decided
        "decision": seed,                # approve | block | hold | reverify
        "decision_at": _now() if seed else None,
        "verification": ver,             # 모국어 발송 케이스(엔진 생성)
        "investigation": inv,            # AI 조사관 브리핑(결정론, 판정 불변)
        "result": r,                     # 엔진 원시 판정
        "turns": [],                     # 고객 답변 의도분류 이력
        "updated_at": _now(),
    }


def _case(persona_id: str) -> dict:
    with _LOCK:
        if persona_id not in _CASES:
            _CASES[persona_id] = _init_case(persona_id)
        return _CASES[persona_id]


class ReplyIn(BaseModel):
    persona_id: str = "minh"
    reply: str


class DecisionIn(BaseModel):
    persona_id: str = "minh"
    decision: str  # approve | block | hold | reverify


# 관제 대기열에 올리는 보류 대상자. 페르소나 2명(주인공) + 가상 고객 3명.
# 순서 = 화면 표시 순서. 주인공 minh 를 맨 위에 둔다.
_QUEUE_IDS = ["minh", "huong", "ramesh", "suman", "cuong"]


@router.get("/queue")
def fraud_queue():
    """콘솔 첫 화면용: 보류 대상자 목록. 각 대상자의 대표 의심 거래와 케이스 상태."""
    if not _engine.available():
        raise HTTPException(503, f"사기탐지 엔진 미로드: {_engine.load_error()}")
    rows = []
    for pid in _QUEUE_IDS:
        sub = _subject(pid)
        if not sub["items"]:
            continue
        item = sub["items"][0]
        case = _case(pid)
        r = case["result"]
        rows.append({
            "persona_id": pid,
            "name": sub["name"],
            "country": sub["country"],
            "visa": sub["visa"],
            "flag": sub["flag"],
            "label": item["label"],
            "amount_krw": item["tx"]["amount"],
            "score": round((r.get("risk_score") or 0) * 100),
            "action": r.get("action"),
            "action_ko": fdata.ACTION_LABELS_KO.get(r.get("action"), r.get("action")),
            "status": case["status"],
            "decision": case["decision"],
        })
    return {"queue": rows}


@router.get("/feed")
def fraud_feed(persona_id: str = "minh"):
    """콘솔 초기 렌더용: 엔진 실채점 피드 + 세그먼트 기준선 + 케이스 상태."""
    if not _engine.available():
        raise HTTPException(503, f"사기탐지 엔진 미로드: {_engine.load_error()}")
    out = _score_feed(persona_id)
    out["case"] = _case(persona_id)
    return out


@router.get("/case")
def fraud_case(persona_id: str = "minh"):
    """콘솔 폴링용: 본인확인 상태와 고객 답변 분류, 분석가 결정."""
    if not _engine.available():
        raise HTTPException(503, f"사기탐지 엔진 미로드: {_engine.load_error()}")
    return _case(persona_id)


@router.post("/reply")
def fraud_reply(body: ReplyIn):
    """고객 폰 답변 -> 엔진 의도분류(강요/원격제어 안전신호 결정론 우선) -> 케이스 갱신."""
    if not _engine.available():
        raise HTTPException(503, f"사기탐지 엔진 미로드: {_engine.load_error()}")
    case = _case(body.persona_id)
    sub = _subject(body.persona_id)
    profile = sub["profile"]
    item = sub["items"][0]
    alert = {
        "tx_id": case["tx_id"],
        "customer_id": body.persona_id,
        "language": profile["language"],
        "amount": item["tx"]["amount"],
        "channel": item["tx"]["channel"],
        "counterparty_country": item["tx"]["counterparty_country"],
        "is_new_device": item["tx"]["is_new_device"],
        "balance_drawdown_ratio": item["tx"]["balance_drawdown_ratio"],
        "triggered_rules": case["result"].get("triggered_rules") or [],
        "verification": case["verification"],
    }
    turn = _engine.chat_turn(alert, body.reply, turn_index=len(case["turns"]) + 1)
    with _LOCK:
        case["turns"].append(turn)
        case["status"] = "replied"
        case["updated_at"] = _now()
    return turn


@router.post("/decision")
def fraud_decision(body: DecisionIn):
    """분석가(사람) 결정 기록. AI 는 결정하지 않는다. reverify 는 본인확인 재발송."""
    if body.decision not in ("approve", "block", "hold", "reverify"):
        raise HTTPException(422, f"알 수 없는 결정: {body.decision}")
    case = _case(body.persona_id)
    with _LOCK:
        if body.decision == "reverify":
            # 모국어 본인확인 재발송: 상태를 다시 verifying 으로
            sub = _subject(body.persona_id)
            case["verification"] = _engine.verify(sub["profile"], sub["items"][0]["tx"])
            case["status"] = "verifying"
            case["decision"] = None
        else:
            case["decision"] = body.decision
            case["decision_at"] = _now()
            case["status"] = "decided"
        case["updated_at"] = _now()
    return case


@router.post("/reset")
def fraud_reset(persona_id: str = "minh"):
    """시연 리허설용 초기화(한 명)."""
    with _LOCK:
        _CASES.pop(persona_id, None)
    return {"ok": True}


@router.post("/reset_all")
def fraud_reset_all():
    """전체 초기화. 콘솔이 켜질 때마다 호출해 대기열을 전원 보류(미결) 상태로 되돌린다.
    서버 프로세스가 결정 상태를 메모리에 들고 있어도 새로 열면 모두 다시 나타난다."""
    with _LOCK:
        _CASES.clear()
    return {"ok": True}
