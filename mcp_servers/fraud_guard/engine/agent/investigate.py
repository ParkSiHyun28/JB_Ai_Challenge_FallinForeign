"""agent/investigate.py — L4 AI 조사관 harness.

Claude/OpenAI 는 사기 판정자가 아니다. core 가 이미 만든 action/룰/모델/설명 증거를
코드가 evidence card 로 정리하고, LLM 은 그 카드에 묶인 "다음 확인 질문"을 생성한다.
키가 없거나 LLM 출력이 깨지면 템플릿으로 폴백한다. core 는 LLM·캐시·상태를 모른다.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import Optional

from contracts.investigation_output import InvestigationOutput
from core.schema import CustomerProfile, ScoreResult, Transaction

PROMPT_VERSION = "investigator-v4-native-lang"
SCHEMA_VERSION = "investigation-output-v2"
# 모국어 질문(예: 베트남어)은 길어서 700 토큰이면 JSON 이 잘려 파싱 실패→조용한 폴백이 된다.
MAX_TOKENS = 2000

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE_DIR = os.path.join(_ROOT, "data", "investigations")

# 고객 대상 확인질문은 고객 모국어로 생성한다(외국인 언어장벽 해결이 핵심 차별점).
# 템플릿 폴백은 한국어 분석가용이며, 모국어 질문은 LLM 모드의 기여다.
_LANG_NAMES = {
    "ko": "Korean", "vi": "Vietnamese", "ne": "Nepali",
    "en": "English", "id": "Indonesian", "zh": "Chinese", "th": "Thai",
}

_RULE_TITLES = {
    "corridor_mismatch": ("제3국 송금", "core.rules:corridor_mismatch"),
    "exit_drawdown": ("출국 임박 잔액 인출", "core.rules:exit_drawdown"),
    "new_device_high_amount": ("신규기기 고액거래", "core.rules:new_device_high_amount"),
    "rapid_passthrough": ("빠른 연속 인출", "core.rules:rapid_passthrough"),
    "night_remittance": ("야간 해외송금", "core.rules:night_remittance"),
    "residency_overstayed": ("체류만료 후 거래", "core.rules:residency_overstayed"),
    "exit_takeover_boost": ("출국기 계좌양도 가중", "core.takeover:exit_takeover_boost"),
}

_CHANNEL_KO = {
    "remittance": "해외 송금",
    "domestic": "국내 이체",
    "atm": "ATM 인출",
}

_ACTION_KO = {
    "allow": "정상 승인",
    "review": "추가 검토",
    "soft_block": "차단 전 보류",
}

_FEATURE_KO = {
    "amount_log": "이체 금액",
    "balance_drawdown_ratio": "잔액 인출 비율",
    "hour": "거래 발생 시각",
    "is_new_device": "신규기기 여부",
    "corridor_match": "평소 송금 경로 일치 여부",
    "tx_velocity_24h": "최근 24시간 거래 수",
    "days_to_residency_end": "체류 만료 잔여일",
}


def _safe_json_loads(text: str) -> Optional[dict]:
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash_evidence(evidence: dict, model: str, reveal_opinion: bool = False) -> str:
    payload = {
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "model": model,
        "reveal_opinion": reveal_opinion,
        "evidence": evidence,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _money(v) -> str:
    return f"{float(v):,.0f}원"


def _pct(v) -> str:
    return f"{float(v):.2f}"


def _channel(v) -> str:
    return _CHANNEL_KO.get(str(v), str(v or "-"))


def _yesno(v) -> str:
    return "예" if bool(v) else "아니오"


def _action(v) -> str:
    return _ACTION_KO.get(str(v), str(v or "-"))


def _feature_name(v) -> str:
    return _FEATURE_KO.get(str(v), str(v or "-"))


def _suspected_type(triggered_rules: list[str], axes: dict) -> str:
    rules = set(triggered_rules)
    if {"exit_drawdown", "corridor_mismatch"} & rules or "exit_takeover_boost" in rules:
        return "exit_period_account_takeover"
    if {"new_device_high_amount", "rapid_passthrough"} & rules:
        return "phishing_or_remote_control"
    if axes.get("model_action") in ("review", "soft_block"):
        return "baseline_anomaly"
    return "unusual_transaction"


def _recommended_action(action: str, suspected_type: str) -> str:
    if action == "soft_block":
        if suspected_type in ("exit_period_account_takeover", "phishing_or_remote_control"):
            return "hold_and_native_language_verify"
        return "hold_and_manual_review"
    if action == "review":
        return "manual_review"
    return "monitor"


def _confidence(action: str, axes: dict, triggered_rules: list[str]) -> str:
    strong_axes = sum(1 for k in ("rule_action", "model_action") if axes.get(k) == "soft_block")
    if action == "soft_block" and (strong_axes >= 2 or len(triggered_rules) >= 3):
        return "high"
    if action in ("soft_block", "review"):
        return "medium"
    return "low"


def _card(card_id: str, kind: str, title: str, fact: str, value, source: str) -> dict:
    return {
        "id": card_id,
        "kind": kind,
        "title": title,
        "fact": fact,
        "value": None if value is None else str(value),
        "source": source,
    }


def _build_key_evidence(evidence: dict) -> list[dict]:
    tx = evidence.get("transaction", {})
    decision = evidence.get("decision", {})
    expl = evidence.get("explanation", {})
    axes = decision.get("axes") or {}
    cards: list[dict] = []

    cards.append(_card("E_TX_1", "transaction", "거래 금액",
                       f"거래 금액은 {_money(tx.get('amount', 0))}입니다.", tx.get("amount"),
                       "transaction.amount"))
    cards.append(_card("E_TX_2", "transaction", "거래 채널과 수취국",
                       f"{_channel(tx.get('channel'))}으로 {tx.get('counterparty_country')} 수취국 거래가 발생했습니다.",
                       tx.get("counterparty_country"), "transaction.channel,counterparty_country"))
    cards.append(_card("E_TX_3", "transaction", "신규기기 여부",
                       f"기존 등록기기가 아닌 새 기기에서 요청되었는지: {_yesno(tx.get('is_new_device'))}.",
                       "신규기기" if bool(tx.get("is_new_device")) else "기존 등록기기",
                       "transaction.is_new_device"))
    cards.append(_card("E_TX_4", "transaction", "잔액 인출률",
                       f"잔액 인출률은 {_pct(tx.get('balance_drawdown_ratio', 0))}입니다.",
                       tx.get("balance_drawdown_ratio"), "transaction.balance_drawdown_ratio"))
    cards.append(_card("E_TX_5", "transaction", "24시간 거래 빈도",
                       f"최근 24시간 거래 수는 {tx.get('tx_velocity_24h')}건입니다.",
                       tx.get("tx_velocity_24h"), "transaction.tx_velocity_24h"))

    for i, rule in enumerate(decision.get("triggered_rules") or [], 1):
        title, source = _RULE_TITLES.get(rule, (rule, f"core.rules:{rule}"))
        cards.append(_card(f"E_RULE_{i}", "rule", title, f"{title} 신호가 발동했습니다.", title, source))

    if decision.get("model_score") is not None:
        cards.append(_card("E_MODEL_1", "model", "모델 분위 점수",
                           f"그룹 정상분포 대비 모델 분위 점수는 {decision.get('model_score')}입니다.",
                           decision.get("model_score"), "core.baseline.percentile"))
    if axes:
        cards.append(_card("E_MODEL_2", "model", "축별 판정",
                           f"룰 기반 판단은 {_action(axes.get('rule_action'))}, 정상분포 모형 판단은 {_action(axes.get('model_action'))}입니다.",
                           None, "core.decision.axes"))

    features = expl.get("features") or {}
    for i, (name, value) in enumerate(features.items(), 1):
        cards.append(_card(f"E_EXPLAIN_{i}", "explain", _feature_name(name),
                           f"{_feature_name(name)} 항목이 이상 판단에 기여했습니다.", value,
                           f"core.explain:{expl.get('explain_method') or 'unknown'}"))
    if expl.get("days_to_residency_end") is not None:
        cards.append(_card("E_PROFILE_1", "profile", "체류 만료 D-day",
                           f"체류 만료까지 {expl.get('days_to_residency_end')}일 남았습니다.",
                           expl.get("days_to_residency_end"), "core.takeover.days_to_residency_end"))
    return cards


def _case_summary(evidence: dict, cards: list[dict]) -> str:
    segment = evidence.get("segment")
    decision = evidence.get("decision", {})
    tx = evidence.get("transaction", {})
    rule_count = len(decision.get("triggered_rules") or [])
    model_score = decision.get("model_score")
    parts = [
        f"{segment} 고객의 {_money(tx.get('amount', 0))} {_channel(tx.get('channel'))} 거래입니다.",
        f"수취국은 {tx.get('counterparty_country')}, 신규기기 여부는 {_yesno(tx.get('is_new_device'))}, "
        f"잔액 인출률={_pct(tx.get('balance_drawdown_ratio', 0))}입니다.",
        f"발동 신호 {rule_count}개와 모델 분위 {model_score}를 근거로 {_action(decision.get('action'))} 판정이 생성되었습니다.",
        "AI 조사관은 이 판정을 바꾸지 않고 후속 확인 질문만 생성합니다.",
    ]
    return " ".join(parts)


def _valid_ids(cards: list[dict]) -> set[str]:
    return {c["id"] for c in cards}


def _default_questions(suspected: str, cards: list[dict]) -> list[dict]:
    ids = [c["id"] for c in cards]
    rule_ids = [c["id"] for c in cards if c["kind"] == "rule"]
    base_ids = ids[:3] or ["E_TX_1"]
    # Q1 은 '왜 확인하는가'를 발동 룰 전체에 근거로 묶는다 → 룰 커버리지 확보 + 근거 강화.
    q1_ids = (rule_ids + base_ids)[:5] if rule_ids else base_ids
    return [
        {
            "id": "Q1",
            "question": "고객이 해당 거래를 직접 지시했는지 모국어로 확인합니다.",
            "purpose": "본인 거래 여부 확인",
            "evidence_ids": q1_ids,
        },
        {
            "id": "Q2",
            "question": "수취인과 거래 목적을 고객에게 확인합니다.",
            "purpose": "수취 관계와 목적 검증",
            "evidence_ids": [i for i in ids if i.startswith("E_TX_")][:2] or base_ids,
        },
        {
            "id": "Q3",
            "question": "최근 기기 변경과 접속 국가가 본인 행동인지 확인합니다.",
            "purpose": "계정 탈취 또는 원격제어 가능성 확인",
            "evidence_ids": [i for i in ids if i in ("E_TX_3", "E_TX_5")] or base_ids,
        },
    ]


def _default_hypotheses(suspected: str, confidence: str, cards: list[dict]) -> list[dict]:
    rule_ids = [c["id"] for c in cards if c["kind"] == "rule"]
    tx_ids = [c["id"] for c in cards if c["kind"] == "transaction"]
    return [{
        "name": suspected,
        "status": "hypothesis",
        "confidence": "low" if confidence == "low" else "medium",
        "supporting_evidence_ids": (rule_ids + tx_ids)[:4] or [cards[0]["id"]],
    }]


def _filter_ids(ids, valid: set[str], fallback: list[str], warnings: list[str], ctx: str) -> list[str]:
    out = [str(i) for i in (ids or []) if str(i) in valid]
    if out:
        return out
    warnings.append(f"{ctx}: evidence_ids repaired")
    return fallback[:2] or list(valid)[:1]


class Investigator:
    """Claude/OpenAI + evidence card + repair + cache harness."""

    def __init__(
        self,
        mode: str = "template",
        model: str = "claude-sonnet-4-6",
        cache_dir: Optional[str] = None,
        reveal_llm_opinion: bool = False,
    ):
        self.mode = mode
        self.model = model
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        # B 플래그: 기본 off(A=Claude는 질문만). on 이면 LLM 가설을 'llm_suggested' 소견으로 병기.
        self.reveal_llm_opinion = reveal_llm_opinion

    def evidence_from_score(
        self,
        tx: Transaction,
        profile: CustomerProfile,
        result: ScoreResult,
        history_summary: Optional[dict] = None,
    ) -> dict:
        axes = (result.explanation or {}).get("axes", {})
        return {
            "tx_id": tx.tx_id,
            "customer_id": profile.customer_id,
            "segment": profile.segment_key,
            "language": profile.language,
            "transaction": {
                "amount": tx.amount,
                "channel": tx.channel,
                "counterparty_country": tx.counterparty_country,
                "ip_country": tx.ip_country,
                "is_new_device": tx.is_new_device,
                "tx_velocity_24h": tx.tx_velocity_24h,
                "balance_drawdown_ratio": tx.balance_drawdown_ratio,
            },
            "decision": {
                "action": result.action,
                "risk_score": result.risk_score,
                "rule_score": result.rule_score,
                "model_score": result.model_score,
                "triggered_rules": list(result.triggered_rules),
                "axes": axes,
            },
            "explanation": {
                "features": (result.explanation or {}).get("features", {}),
                "explain_method": (result.explanation or {}).get("explain_method"),
                "takeover_boost": (result.explanation or {}).get("takeover_boost"),
                "days_to_residency_end": (result.explanation or {}).get("days_to_residency_end"),
            },
            "history_summary": history_summary or {},
        }

    def evidence_from_alert(self, alert: dict) -> dict:
        return {
            "tx_id": alert.get("id"),
            "customer_id": alert.get("customer_id"),
            "segment": alert.get("segment"),
            "language": alert.get("language"),
            "transaction": {
                "amount": alert.get("amount"),
                "channel": alert.get("channel"),
                "counterparty_country": alert.get("counterparty_country"),
                "ip_country": alert.get("ip_country"),
                "is_new_device": alert.get("is_new_device"),
                "tx_velocity_24h": alert.get("tx_velocity_24h"),
                "balance_drawdown_ratio": alert.get("balance_drawdown_ratio"),
            },
            "decision": {
                "action": alert.get("action"),
                "risk_score": alert.get("risk_score"),
                "rule_score": alert.get("rule_score"),
                "model_score": alert.get("model_pctl"),
                "triggered_rules": list(alert.get("triggered_rules") or []),
                "axes": {
                    "rule_action": alert.get("rule_action"),
                    "model_action": alert.get("model_action"),
                    "model_pctl": alert.get("model_pctl"),
                },
            },
            "explanation": {
                "features": alert.get("explanation") or {},
                "explain_method": alert.get("explain_method"),
                "takeover_boost": alert.get("takeover_boost"),
                "days_to_residency_end": alert.get("days_to_residency_end"),
            },
            "history_summary": alert.get("history_summary") or {},
        }

    def _cache_path(self, evidence_hash: str) -> str:
        return os.path.join(self.cache_dir, f"{evidence_hash}.json")

    def _load_cache(self, evidence_hash: str) -> Optional[dict]:
        path = self._cache_path(evidence_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _save_cache(self, evidence_hash: str, raw_report: dict) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_path(evidence_hash), "w", encoding="utf-8") as f:
                json.dump(raw_report, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
        except OSError:
            pass

    def _base_output(self, evidence: dict, cards: list[dict], evidence_hash: str, generated_by: str,
                     llm_status: str, repair_warnings: Optional[list[str]] = None) -> dict:
        decision = evidence.get("decision", {})
        axes = decision.get("axes") or {}
        rules = list(decision.get("triggered_rules") or [])
        suspected = _suspected_type(rules, axes)
        confidence = _confidence(decision.get("action") or "allow", axes, rules)
        action = _recommended_action(decision.get("action") or "allow", suspected)
        questions = _default_questions(suspected, cards)
        hypotheses = _default_hypotheses(suspected, confidence, cards)
        summary = _case_summary(evidence, cards)
        return {
            "tx_id": evidence.get("tx_id"),
            "customer_id": evidence.get("customer_id"),
            "case_summary": summary,
            "risk_narrative": summary,
            "key_evidence": cards,
            "hypotheses": hypotheses,
            "llm_suggested_hypotheses": [],
            "verification_questions": questions,
            "recommended_next_action": action,
            "confidence": confidence,
            "evidence": evidence,
            "evidence_hash": evidence_hash,
            "generated_by": generated_by,
            "llm_status": llm_status,
            "repair_warnings": repair_warnings or [],
            # Backward-compatible aliases.
            "suspected_type": suspected,
            "recommended_action": action,
            "needed_checks": [q["question"] for q in questions],
        }

    def _prompt(self, evidence: dict, cards: list[dict]) -> str:
        # 코드가 결정하는 것(action·confidence·suspected_type)은 요청하지 않는다.
        # LLM 은 확인 질문만 생성한다(B 플래그 시 비권위 가설도).
        lang = evidence.get("language") or "ko"
        lang_name = _LANG_NAMES.get(lang, "the customer's native language")
        schema = {
            "verification_questions": [
                {"question": f"question written in {lang_name}",
                 "purpose": "why ask it (Korean, for the analyst)", "evidence_ids": ["E_TX_1"]}
            ],
        }
        instr = (
            "You are a bank fraud investigation assistant. You do NOT decide fraud, "
            "do NOT choose the action, and do NOT score risk — code already decided those. "
            f"Write every verification question in {lang_name} so the foreign customer can answer it; "
            "keep the 'purpose' field in Korean for the analyst, as one short phrase (max ~15 words), not a paragraph. "
            "Generate questions only from the evidence cards. "
            "Do not invent customer history, statistics, legal conclusions, or facts outside the cards. "
            "Every question must cite existing evidence_ids. "
        )
        if self.reveal_llm_opinion:
            schema["hypotheses"] = [
                {"name": "snake_case_hypothesis", "confidence": "low|medium",
                 "supporting_evidence_ids": ["E_RULE_1"]}
            ]
            instr += "Hypotheses are non-authoritative notes and must also cite existing evidence_ids. "
        return (
            instr
            + "Return valid JSON only with this schema:\n"
            + f"{json.dumps(schema, ensure_ascii=False)}\n\n"
            + "Evidence cards:\n"
            + f"{json.dumps(cards, ensure_ascii=False, default=str)}\n\n"
            + "Case metadata:\n"
            + f"{json.dumps(evidence, ensure_ascii=False, default=str)}"
        )

    def _claude_report(self, evidence: dict, cards: list[dict]) -> Optional[dict]:
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": self._prompt(evidence, cards)}],
            )
            text = msg.content[0].text.strip()
            return _safe_json_loads(text)
        except Exception:
            return None

    def _openai_report(self, evidence: dict, cards: list[dict]) -> Optional[dict]:
        base_url = os.environ.get("FRAUDGUARD_LLM_BASE_URL")
        if not base_url:
            return None
        api_key = os.environ.get("FRAUDGUARD_LLM_API_KEY", "not-needed")
        model = os.environ.get("FRAUDGUARD_LLM_MODEL", self.model)
        payload = json.dumps({
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": self._prompt(evidence, cards)}],
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                     "User-Agent": "fraud-guard/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return _safe_json_loads((data["choices"][0]["message"]["content"] or "").strip())
        except Exception:
            return None

    def _repair_report(self, raw: Optional[dict], base: dict) -> dict:
        if raw is None:
            return base
        warnings = list(base.get("repair_warnings") or [])
        valid = _valid_ids(base["key_evidence"])
        fallback_ids = list(valid)[:3]

        questions = []
        raw_questions = raw.get("verification_questions") or raw.get("needed_checks") or []
        if isinstance(raw_questions, list):
            for i, q in enumerate(raw_questions[:5], 1):
                if isinstance(q, str):
                    question, purpose, ids = q, "LLM generated verification question", fallback_ids
                    warnings.append(f"Q{i}: string question repaired")
                elif isinstance(q, dict):
                    question = str(q.get("question") or q.get("text") or "").strip()
                    purpose = str(q.get("purpose") or "확인 필요").strip()
                    ids = q.get("evidence_ids") or q.get("evidence_refs") or []
                else:
                    continue
                if not question:
                    warnings.append(f"Q{i}: blank question dropped")
                    continue
                questions.append({
                    "id": f"Q{i}",
                    "question": question,
                    "purpose": purpose or "확인 필요",
                    "evidence_ids": _filter_ids(ids, valid, fallback_ids, warnings, f"Q{i}"),
                })
        if questions:
            base["verification_questions"] = questions
            base["needed_checks"] = [q["question"] for q in questions]
        else:
            warnings.append("verification_questions: missing, template defaults used")

        # hypotheses 는 항상 코드 소유(_default_hypotheses). LLM 가설은 절대 여기 섞지 않는다.
        # reveal_llm_opinion(B)일 때만 별도 필드 llm_suggested_hypotheses 로 분리해 스키마 레벨에서
        # "코드 단정"과 구분한다 — 소비자가 source 배지를 무시해도 필드 이름으로 혼동 불가.
        if self.reveal_llm_opinion:
            suggested = []
            raw_hypotheses = raw.get("hypotheses") or []
            if isinstance(raw_hypotheses, list):
                for i, h in enumerate(raw_hypotheses[:3], 1):
                    if not isinstance(h, dict):
                        continue
                    name = str(h.get("name") or h.get("type") or "").strip()
                    if not name:
                        warnings.append(f"H{i}: blank hypothesis dropped")
                        continue
                    ids = h.get("supporting_evidence_ids") or h.get("evidence_ids") or []
                    confidence = str(h.get("confidence") or "low")
                    suggested.append({
                        "name": name,
                        "status": "hypothesis",
                        "confidence": confidence if confidence in ("low", "medium", "high") else "low",
                        "supporting_evidence_ids": _filter_ids(ids, valid, fallback_ids, warnings, f"H{i}"),
                        "source": "llm_suggested",
                    })
            if suggested:
                base["llm_suggested_hypotheses"] = suggested

        # recommended_next_action·confidence·suspected_type 는 100% 코드가 결정(_base_output).
        # LLM 값을 받지 않는다 — override 하면 "코드가 결정, LLM은 질문" 원칙이 코드에서 새어버린다.
        base["repair_warnings"] = warnings
        if raw:
            base["llm_status"] = "ok" if not warnings else "repaired"
        return base

    def investigate_evidence(self, evidence: dict) -> dict:
        cards = _build_key_evidence(evidence)
        evidence = dict(evidence)
        evidence["key_evidence"] = cards
        evidence_hash = _hash_evidence(evidence, self.model, self.reveal_llm_opinion)

        cached = None
        if self.mode in ("claude", "cached_claude"):
            cached = self._load_cache(evidence_hash)
        if cached is not None:
            base = self._base_output(evidence, cards, evidence_hash, "cached_claude", "cached")
            return InvestigationOutput(**self._repair_report(cached, base)).dict()
        if self.mode == "cached_claude":
            base = self._base_output(
                evidence, cards, evidence_hash, "template", "cache_miss_fallback",
                ["cache miss: template fallback"],
            )
            return InvestigationOutput(**base).dict()

        raw, generated_by, status = None, "template", "template"
        if self.mode == "claude":
            raw = self._claude_report(evidence, cards)
            if raw is not None:
                generated_by, status = "live_claude", "ok"
                self._save_cache(evidence_hash, raw)
        elif self.mode == "openai":
            raw = self._openai_report(evidence, cards)
            if raw is not None:
                generated_by, status = "live_openai", "ok"

        if raw is None and self.mode in ("claude", "openai"):
            status = "llm_unavailable_fallback"
        base = self._base_output(evidence, cards, evidence_hash, generated_by, status)
        repaired = self._repair_report(raw, base)
        return InvestigationOutput(**repaired).dict()

    def request(self, tx: Transaction, profile: CustomerProfile, result: ScoreResult,
                history_summary: Optional[dict] = None) -> dict:
        return self.investigate_evidence(self.evidence_from_score(tx, profile, result, history_summary))

    def request_from_alert(self, alert: dict) -> dict:
        return self.investigate_evidence(self.evidence_from_alert(alert))
