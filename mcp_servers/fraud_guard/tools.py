"""사기탐지 부문 tool 4개. 순수 함수다. MCP 나 Claude 를 모른다.
입력은 키워드 인자, 출력은 {summary, detail, numbers, card} dict.

이 부문은 팀원이 만든 진짜 4계층 ML 엔진(engine/)을 감싼다. tool 은 dict 경계 변환과
한국어 카드 포매팅만 하고, 판정과 점수는 전부 엔진이 계산한다.
- 첫 인자는 항상 persona_id("minh"/"suman" 또는 동적 id).
- 페르소나(flag/visa/출국일)를 엔진 프로필로 매핑해(_data.persona_to_profile) 엔진에 넣는다.
- 판정 근거가 없으면(거래 없음, 엔진 미로드) 추측하지 않고 정직하게 안내한다.
- 결정권(승인/차단/보류)은 사람 분석가 몫이다. tool 은 판정 제안과 근거만 만든다.
"""
from __future__ import annotations

from shared.personas import get_persona

from . import data
from . import _engine

_LANG_KO = {"vi": "베트남어", "ne": "네팔어", "ko": "한국어", "en": "영어"}


def _rules_ko(triggered: list) -> list:
    return [data.RULE_LABELS_KO.get(r, r) for r in triggered]


def _engine_down_card(name: str) -> dict:
    """엔진 미로드 시 안전 4키 응답. 앱을 죽이지 않고 사유를 남긴다."""
    return {
        "summary": "사기탐지 엔진을 불러오지 못했습니다.",
        "detail": (
            f"학습모델 또는 의존성(scikit-learn/joblib) 로드에 실패해 {name} 채점을 건너뜁니다. "
            f"사유: {_engine.load_error()}. requirements.txt 설치 후 다시 시도하세요."
        ),
        "numbers": {"engine_available": False},
        "card": None,
    }


def _no_tx_card(p: dict, name: str) -> dict:
    return {
        "summary": f"{p['name']}님은 {name} 대상 거래가 없습니다.",
        "detail": "실시간 거래 피드에 등록된 의심 거래가 없어 채점하지 않습니다.",
        "numbers": {"tx_id": None, "score": None, "action": None},
        "card": None,
    }


def _pick_tx(persona_id: str, tx_id):
    feed = data.demo_feed(persona_id)
    if not feed:
        return None
    if tx_id:
        for item in feed:
            if item["tx"]["tx_id"] == tx_id:
                return item
        return None
    return feed[0]


def _core_numbers(r: dict, item: dict) -> dict:
    """엔진 원시 결과 -> 화면/수치용 numbers dict."""
    axes = (r.get("explanation") or {}).get("axes", {})
    return {
        "tx_id": r.get("tx_id"),
        "label": item["label"],
        "amount_krw": item["tx"]["amount"],
        "score": round((r.get("risk_score") or 0) * 100),
        "risk_score": r.get("risk_score"),
        "rule_score": r.get("rule_score"),
        "model_score": r.get("model_score"),
        "action": r.get("action"),
        "rule_action": axes.get("rule_action"),
        "model_action": axes.get("model_action"),
        "triggered_rules": list(r.get("triggered_rules") or []),
        "engine_available": True,
    }


# ---------------------------------------------------------------------------
def score_transaction(persona_id: str, tx_id: str = None) -> dict:
    """거래 1건의 위험 점수를 엔진(L1 룰 + L2 정상분포 + L3 앙상블)으로 매긴다."""
    p = get_persona(persona_id)
    if not _engine.available():
        return _engine_down_card("위험 점수")
    item = _pick_tx(persona_id, tx_id)
    if item is None:
        return _no_tx_card(p, "위험 점수")

    profile = data.persona_to_profile(p)
    r = _engine.score(profile, item["tx"])
    nums = _core_numbers(r, item)
    action_ko = data.ACTION_LABELS_KO.get(r.get("action"), r.get("action"))
    rules_ko = _rules_ko(nums["triggered_rules"])
    amt = data.won(nums["amount_krw"])

    if r.get("action") == "allow":
        return {
            "summary": f"{item['label']}({amt})는 위험 점수 {nums['score']}점으로 정상 범위입니다.",
            "detail": (
                f"룰축과 정상분포모형 모두 이상 신호가 약합니다. "
                f"엔진 판정은 정상 통과이며 별도 조치가 필요 없습니다."
            ),
            "numbers": nums,
            "card": None,
        }

    reason = " / ".join(rules_ko) if rules_ko else "정상분포 대비 이상"
    return {
        "summary": f"{item['label']}({amt})는 위험 점수 {nums['score']}점으로 {action_ko} 대상입니다.",
        "detail": (
            f"발동 근거는 {reason}입니다. 룰축 판정은 {data.ACTION_LABELS_KO.get(nums['rule_action'], nums['rule_action'])}, "
            f"정상분포모형 판정은 {data.ACTION_LABELS_KO.get(nums['model_action'], nums['model_action'])}이며 "
            f"두 축의 상위값으로 최종 {action_ko}를 제안합니다. 최종 결정은 분석가가 합니다."
        ),
        "numbers": nums,
        "card": {
            "icon": "",
            "head": f"위험 점수 {nums['score']}점 - {action_ko}",
            "body": f"{item['label']} {amt}. 근거 {reason}.",
            "metric": f"발동 룰 {len(rules_ko)}종",
        },
    }


# ---------------------------------------------------------------------------
def detect_account_takeover(persona_id: str) -> dict:
    """대표 의심 거래에 출국기 계좌양도 특화 가중(D-day 지수감쇠)을 적용해 탐지한다."""
    p = get_persona(persona_id)
    if not _engine.available():
        return _engine_down_card("계좌양도 탐지")
    item = data.hero_tx(persona_id)
    if item is None:
        return _no_tx_card(p, "계좌양도 탐지")

    profile = data.persona_to_profile(p)
    r = _engine.takeover(profile, item["tx"])
    nums = _core_numbers(r, item)
    suspected = r.get("action") == "soft_block"
    nums["takeover_suspected"] = suspected
    amt = data.won(nums["amount_krw"])
    rules_ko = _rules_ko(nums["triggered_rules"])
    reason = " / ".join(rules_ko) if rules_ko else "정상분포 대비 이상"

    if not suspected:
        return {
            "summary": f"{p['name']}님 거래에서 계좌양도 패턴이 확정되지 않았습니다.",
            "detail": f"위험 점수 {nums['score']}점. 계좌양도로 볼 근거가 부족해 즉시 보류 대상은 아닙니다.",
            "numbers": nums,
            "card": None,
        }

    return {
        "summary": f"{p['name']}님 계좌에서 계좌양도 의심 거래를 탐지했습니다. 즉시 보류합니다.",
        "detail": (
            f"{item['label']} {amt}. 출국 임박 시점에 새 기기로 잔액 전액을 옮기는 패턴이라 "
            f"계좌양도(명의도용) 가중이 적용됐습니다. 근거는 {reason}입니다. "
            f"모국어 본인확인을 보내 고객 의사를 확인하도록 권고합니다."
        ),
        "numbers": nums,
        "card": {
            "icon": "",
            "head": f"계좌양도 의심 - 위험 {nums['score']}점 보류",
            "body": f"{item['label']} {amt}. {reason}.",
            "metric": "모국어 본인확인 권고",
        },
    }


# ---------------------------------------------------------------------------
def request_verification(persona_id: str) -> dict:
    """보류 거래에 고객 모국어 본인확인 메시지를 만든다(템플릿 모드, 무설치 동작)."""
    p = get_persona(persona_id)
    if not _engine.available():
        return _engine_down_card("본인확인")
    item = data.hero_tx(persona_id)
    if item is None:
        return _no_tx_card(p, "본인확인")

    profile = data.persona_to_profile(p)
    case = _engine.verify(profile, item["tx"])
    lang = case.get("language", profile["language"])
    lang_ko = _LANG_KO.get(lang, lang)
    amt = data.won(item["tx"]["amount"])
    numbers = {
        "delivered": True,
        "tx_id": case.get("tx_id"),
        "amount_krw": item["tx"]["amount"],
        "language": lang,
        "language_ko": lang_ko,
        "status": case.get("status"),
        "generated_by": case.get("generated_by"),
        "engine_available": True,
    }
    return {
        "summary": f"{p['name']}님에게 {lang_ko} 본인확인 메시지를 발송했습니다.",
        "detail": (
            f"보류한 {amt} 거래에 대해 고객 모국어인 {lang_ko}로 본인확인을 보냈습니다. "
            f"한국어 안내만으로는 강요와 기망 여부 확인이 어렵기 때문입니다. "
            f"발송 문구: {case.get('message')}"
        ),
        "numbers": numbers,
        "card": {
            "icon": "",
            "head": f"{lang_ko} 본인확인 발송 완료",
            "body": f"{amt} 보류 거래에 모국어 본인확인을 보냈습니다. 고객 응답을 기다립니다.",
            "metric": f"발송 언어 {lang_ko}",
        },
    }


# ---------------------------------------------------------------------------
def register_baseline(persona_id: str) -> dict:
    """페르소나 국적/비자 세그먼트의 학습된 정상분포 기준선(임계)을 조회한다."""
    p = get_persona(persona_id)
    if not _engine.available():
        return _engine_down_card("기준선 조회")
    profile = data.persona_to_profile(p)
    seg = f"{profile['nationality']}:{profile['visa_type']}"
    th = _engine.baseline_thresholds(seg)
    if th is None:
        return {
            "summary": f"{p['country']} {p['visa']} 세그먼트({seg})는 학습된 정상분포가 없습니다.",
            "detail": "미학습 세그먼트라 정상분포모형 축은 비활성이고 룰축만으로 판정합니다.",
            "numbers": {"segment_key": seg, "trained": False},
            "card": None,
        }
    return {
        "summary": f"{p['country']} {p['visa']} 세그먼트({seg}) 정상분포 기준선을 확인했습니다.",
        "detail": (
            f"이 세그먼트는 정상 거래 분포로 Isolation Forest 를 학습했습니다. "
            f"추가 검토 임계는 분위 {th['review']}, 즉시 보류 임계는 분위 {th['soft_block']}입니다. "
            f"분위 임계는 오탐률만 통제하며 사기 적발률과 섞지 않습니다."
        ),
        "numbers": {
            "segment_key": seg,
            "trained": True,
            "review_threshold": th["review"],
            "soft_block_threshold": th["soft_block"],
        },
        "card": {
            "icon": "",
            "head": f"{seg} 정상분포 학습 완료",
            "body": "국적과 비자 세그먼트별로 정상 거래 분포를 학습해 오탐을 통제합니다.",
            "metric": f"보류 임계 분위 {th['soft_block']}",
        },
    }


# tool 레지스트리. shared/registry.py 가 자동 발견해 backend 와 병합한다.
TOOL_REGISTRY = {
    "register_baseline": register_baseline,
    "score_transaction": score_transaction,
    "detect_account_takeover": detect_account_takeover,
    "request_verification": request_verification,
}

# 능동 모드에서 먼저 부르는 트리거 tool.
ACTIVE_TOOLS = ["score_transaction", "detect_account_takeover"]
