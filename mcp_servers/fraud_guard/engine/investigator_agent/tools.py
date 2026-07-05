"""investigator_agent/tools.py — 에이전트가 호출하는 read-only 도구 정의 + 실행기.

도구는 전부 **근거 조회**다(판정을 바꾸는 도구 없음). 마지막 submit_investigation 만
'쓰기'인데, 그것도 사람이 볼 확인질문/가설을 기록할 뿐 core 의 action 을 건드리지 않는다.

증거 카드·evidence dict 는 agent/investigate.py 의 단일 소스를 재사용한다(train/serve 처럼
설명 스키마도 두 군데 적으면 skew 나므로). core.config 로 룰 임계값을 읽어 근거를 확정한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from agent import investigate as _inv  # evidence/card 단일 소스 재사용
from core.config import load_rule_params
from core.schema import CustomerProfile, ScoreResult, Transaction

# 룰별 '의미/이유' — rules.yaml 의 rationale 를 조사관용으로 요약(근거 확정, LLM 환각 방지).
_RULE_MEANINGS: dict[str, tuple[str, str]] = {
    "corridor_mismatch": (
        "해외송금이 평소 corridor(본국)이 아닌 제3국 계좌로 나갔다.",
        "출국기 계좌양도는 잔액을 제3국으로 빼는 경우가 많다(시나리오 A)."),
    "exit_drawdown": (
        "체류 만료가 임박한 시점에 잔액을 대부분 인출/이체했다.",
        "출국 직전 계좌를 넘기며 잔액을 일괄 정리하는 양도 패턴."),
    "new_device_high_amount": (
        "기존 등록기기가 아닌 새 기기에서 고액 거래가 요청됐다.",
        "계좌 탈취/양도 시 새 기기·새 접속환경이 동반된다."),
    "rapid_passthrough": (
        "짧은 시간 다회 거래로 입금 직후 잔액을 즉시 통과이체했다.",
        "인출책/통장대여·피싱 자금세탁의 전형(금감원 패턴)."),
    "night_remittance": (
        "야간 시간대에 해외송금이 발생했다.",
        "본인 아닌 조작 세력의 원격 인출이 야간에 몰리는 경향."),
    "residency_overstayed": (
        "체류자격이 이미 만료된 상태에서 금융활동이 있었다.",
        "만료 후 계좌는 대여/양도 고위험(정상 사용 동기 약함)."),
    "exit_takeover_boost": (
        "출국 임박 D-day 가중으로 위험도가 보류선 위로 올라갔다.",
        "출국기 계좌양도 특화 가중(비선형 D-day)."),
}


@dataclass
class ToolContext:
    """한 알림(거래 1건) 조사에 필요한 read-only 근거 묶음 + submit 결과 홀더."""

    evidence: dict                         # investigate.evidence_from_score 와 동일 스키마
    cards: list[dict]                      # investigate._build_key_evidence 산출
    language: str = "ko"
    submitted: Optional[dict] = None       # submit_investigation 이 채운다(터미널)
    _rule_params: object = field(default=None, repr=False)

    @classmethod
    def from_score(cls, tx: Transaction, profile: CustomerProfile,
                   result: ScoreResult, today: Optional[date] = None,
                   history_summary: Optional[dict] = None) -> "ToolContext":
        inv = _inv.Investigator(mode="template")  # LLM 안 씀 — 증거 정리 헬퍼로만 사용
        evidence = inv.evidence_from_score(tx, profile, result, history_summary)
        cards = _inv._build_key_evidence(evidence)
        return cls(evidence=evidence, cards=cards, language=profile.language,
                   _rule_params=load_rule_params())

    @classmethod
    def from_alert(cls, alert: dict) -> "ToolContext":
        """게이트웨이 알림 dict → 조사 컨텍스트. 증거/카드는 investigate 단일 소스 재사용."""
        inv = _inv.Investigator(mode="template")
        evidence = inv.evidence_from_alert(alert)
        cards = _inv._build_key_evidence(evidence)
        return cls(evidence=evidence, cards=cards, language=alert.get("language", "ko"),
                   _rule_params=load_rule_params())

    # --- 도구 실행 (이름 → dict 결과) ---
    def run(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"_tool_{name}", None)
        if fn is None:
            return {"error": f"unknown tool '{name}'"}
        try:
            return fn(args)
        except Exception as e:  # 도구 오류는 is_error 로 모델에 되돌려 회복시킨다
            return {"error": f"{type(e).__name__}: {e}"}

    def _tool_get_case_overview(self, _args: dict) -> dict:
        d = self.evidence.get("decision", {})
        tx = self.evidence.get("transaction", {})
        return {
            "note": "action/risk_score 는 결정론 코드가 이미 확정했다. 바꾸지 말 것.",
            "action": d.get("action"),
            "risk_score": d.get("risk_score"),
            "rule_score": d.get("rule_score"),
            "model_pctl": d.get("model_score"),
            "triggered_rules": d.get("triggered_rules", []),
            "segment": self.evidence.get("segment"),
            "language": self.language,
            "amount": tx.get("amount"),
            "counterparty_country": tx.get("counterparty_country"),
        }

    def _tool_list_evidence_cards(self, _args: dict) -> dict:
        return {"cards": self.cards}

    def _tool_explain_rule(self, args: dict) -> dict:
        rule = str(args.get("rule_name", "")).strip()
        meaning = _RULE_MEANINGS.get(rule)
        if meaning is None:
            return {"error": f"unknown rule '{rule}'",
                    "known_rules": sorted(_RULE_MEANINGS)}
        p = self._rule_params
        thresholds = {
            "dday_window_days": p.dday_window_days,
            "high_amount_krw": p.high_amount_krw,
            "night_hours": list(p.night_hours),
            "exit_drawdown_min": p.exit_drawdown_min,
            "rapid_velocity_min": p.rapid_velocity_min,
            "rapid_drawdown_min": p.rapid_drawdown_min,
            "penalty": p.penalty.get(rule),
        }
        return {"rule": rule, "means": meaning[0], "why_it_matters": meaning[1],
                "config_thresholds": thresholds,
                "triggered": rule in (self.evidence.get("decision", {}).get("triggered_rules") or [])}

    def _tool_get_group_baseline(self, _args: dict) -> dict:
        expl = self.evidence.get("explanation", {})
        return {
            "segment": self.evidence.get("segment"),
            "model_pctl": self.evidence.get("decision", {}).get("model_score"),
            "note": ("model_pctl 는 '그룹 정상분포 대비 분위'다. None 이면 그 그룹은 "
                     "아직 미학습(기준선 없음)이라 모델축은 무신호 — 룰축만으로 판정된 것."),
            "explain_method": expl.get("explain_method"),
            "feature_contributions": expl.get("features", {}),
            "policy": {"review_quantile": 0.95, "soft_block_quantile": 0.99,
                       "meaning": "분위수는 오탐(FPR)만 통제. Recall 보장 아님."},
        }

    def _tool_submit_investigation(self, args: dict) -> dict:
        valid_ids = {c["id"] for c in self.cards}

        def _clean_ids(ids):
            out = [str(i) for i in (ids or []) if str(i) in valid_ids]
            return out or sorted(valid_ids)[:1]

        questions = []
        for q in (args.get("verification_questions") or [])[:5]:
            if not isinstance(q, dict):
                continue
            question = str(q.get("question", "")).strip()
            if not question:
                continue
            questions.append({
                "question": question,
                "purpose": str(q.get("purpose", "확인 필요")).strip(),
                "evidence_ids": _clean_ids(q.get("evidence_ids")),
            })
        hypotheses = []
        for h in (args.get("hypotheses") or [])[:4]:
            if not isinstance(h, dict):
                continue
            name = str(h.get("name", "")).strip()
            if not name:
                continue
            conf = h.get("confidence")
            hypotheses.append({
                "name": name,
                "status": "hypothesis",
                "confidence": conf if conf in ("low", "medium") else "low",
                "supporting_evidence_ids": _clean_ids(h.get("supporting_evidence_ids")),
                "source": "llm_suggested",  # 비권위 — 코드 단정과 분리(계약과 동일 규약)
            })
        self.submitted = {
            "verification_questions": questions,
            "llm_suggested_hypotheses": hypotheses,
            "recommended_next_check": str(args.get("recommended_next_check", "")).strip(),
            "confidence": args.get("confidence") if args.get("confidence") in
            ("low", "medium", "high") else "low",
        }
        return {"status": "recorded",
                "note": "조사 요약이 기록됐다. 더 질문할 게 없으면 이번 턴을 종료하라.",
                "questions_recorded": len(questions),
                "hypotheses_recorded": len(hypotheses)}


# --- Anthropic tool 스키마 (input_schema = JSON Schema) ---
_KNOWN_RULES = sorted(_RULE_MEANINGS)

TOOLS: list[dict] = [
    {
        "name": "get_case_overview",
        "description": ("이 거래에 대해 결정론 코드가 이미 내린 판정(action/risk_score/발동룰)과 "
                        "세그먼트·고객 모국어를 조회한다. 조사 시작 시 먼저 호출하라. "
                        "판정을 바꾸지 말 것 — 너는 후속 확인 질문만 만든다."),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_evidence_cards",
        "description": ("코드가 만든 원증거 카드 목록(id·kind·title·fact·value·source)을 조회한다. "
                        "모든 확인 질문은 여기의 evidence_ids 를 인용해야 한다."),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "explain_rule",
        "description": ("발동한 룰 하나의 의미·왜 위험한지·config 임계값을 조회한다. "
                        "카드에서 본 룰을 이해하려면 이걸 호출하라(추측 금지)."),
        "input_schema": {
            "type": "object",
            "properties": {"rule_name": {"type": "string", "enum": _KNOWN_RULES,
                                         "description": "설명이 필요한 발동 룰 이름"}},
            "required": ["rule_name"], "additionalProperties": False,
        },
    },
    {
        "name": "get_group_baseline",
        "description": ("이 고객 그룹(국적×비자)의 정상분포 대비 모델 분위·피처 기여·임계 정책을 조회한다. "
                        "'평소와 무엇이 다른가'를 확인할 때 호출하라."),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "submit_investigation",
        "description": ("근거가 충분하면 이 도구로 조사 결과를 제출하고 조사를 끝낸다. "
                        "verification_questions 는 반드시 고객 모국어로, purpose 는 한국어로 작성. "
                        "hypotheses 는 단정이 아니라 낮은/중간 확신의 비권위 후보다."),
        "input_schema": {
            "type": "object",
            "properties": {
                "verification_questions": {
                    "type": "array", "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "고객 모국어로 쓴 확인 질문"},
                            "purpose": {"type": "string", "description": "분석가용 한국어 목적(짧게)"},
                            "evidence_ids": {"type": "array", "items": {"type": "string"},
                                             "description": "이 질문의 근거 카드 id들"},
                        },
                        "required": ["question", "purpose", "evidence_ids"],
                    },
                },
                "hypotheses": {
                    "type": "array", "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "snake_case 가설명"},
                            "confidence": {"type": "string", "enum": ["low", "medium"]},
                            "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "confidence", "supporting_evidence_ids"],
                    },
                },
                "recommended_next_check": {"type": "string",
                                           "description": "분석가가 다음에 할 점검(한국어)"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["verification_questions", "recommended_next_check", "confidence"],
        },
    },
]


def tools_json() -> str:
    """디버그용 — 도구 스키마 pretty print."""
    return json.dumps(TOOLS, ensure_ascii=False, indent=2)
