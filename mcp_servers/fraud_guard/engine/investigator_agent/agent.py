"""investigator_agent/agent.py — 자율 tool-calling 루프 조사 에이전트 (옵션 2 핵심).

manual agentic loop:
  1) Claude 에 도구 목록과 함께 케이스를 준다.
  2) Claude 가 read-only 도구를 호출(get_case_overview / list_evidence_cards /
     explain_rule / get_group_baseline)하며 스스로 근거를 모은다.
  3) 충분해지면 submit_investigation 을 호출 → 결과 기록 후 종료.
루프는 stop_reason=="end_turn" 이거나 submit 후 종료 신호, 또는 max_turns 에서 끝난다.

모델·thinking 규약(claude-api 스킬 기준):
  - model = claude-opus-4-8 (기본; 필요시 교체)
  - thinking = {"type": "adaptive"}  (Opus 4.8 는 budget_tokens 미지원, adaptive 만)
  - 판정은 코드가 이미 함 → 에이전트는 근거수집·질문생성만(system 프롬프트로 강제)

anthropic 미설치/키 없음이면 명확한 예외를 던진다(조용한 폴백 없음 — 데모가 안내).
core 는 이 모듈을 모른다(단방향 의존).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .tools import TOOLS, ToolContext

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 8000
MAX_TURNS = 10  # 도구 왕복 상한(무한루프 방지)

_LANG_NAMES = {
    "ko": "Korean (한국어)", "vi": "Vietnamese (Tiếng Việt)",
    "ne": "Nepali (नेपाली, Devanagari script)", "en": "English",
    "id": "Indonesian", "zh": "Chinese", "th": "Thai",
}

_SYSTEM = """\
You are a bank fraud INVESTIGATION PLANNER for a foreigner-focused FDS.

Hard rules (non-negotiable):
- You do NOT decide fraud. You do NOT choose or change the action
  (allow/review/soft_block) and you do NOT score risk. Deterministic code has
  already decided those; treat them as fixed facts.
- Your job is to plan the investigation: gather evidence with the read-only
  tools, then produce native-language verification questions and
  non-authoritative hypotheses for a human analyst.
- Ground everything in evidence cards. Every verification question must cite
  existing evidence_ids. Do not invent customer history, statistics, or facts
  that are not in the tools' output.

How to work:
1. Call get_case_overview first, then list_evidence_cards.
2. For each triggered rule you don't fully understand, call explain_rule.
   Call get_group_baseline to see how this transaction differs from the group norm.
3. When you have enough grounded understanding, call submit_investigation ONCE
   and then end your turn. Do not keep calling tools after submitting.

Writing the questions:
- Write every verification question in {lang_name} so the foreign customer can
  answer it directly. Keep each 'purpose' field in Korean for the analyst, one
  short phrase.
- Hypotheses are LOW/MEDIUM confidence candidates, never assertions.
- Keep the whole investigation tight: at most 3-4 questions.
"""


@dataclass
class InvestigationResult:
    """에이전트 1회 실행 결과 — 산출물 + 관측 가능한 루프 궤적."""

    tx_id: str
    submitted: Optional[dict]           # ToolContext.submitted (질문·가설·다음점검)
    tool_calls: list[dict] = field(default_factory=list)  # [{turn, name, input}]
    turns: int = 0
    stop_reason: Optional[str] = None
    model: str = DEFAULT_MODEL

    @property
    def ok(self) -> bool:
        return bool(self.submitted and self.submitted.get("verification_questions"))


class InvestigatorAgent:
    def __init__(self, model: str = DEFAULT_MODEL, max_turns: int = MAX_TURNS):
        self.model = model
        self.max_turns = max_turns

    def _client(self):
        try:
            from anthropic import Anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "이 에이전트는 실제 Claude tool-calling 루프다 — `pip install anthropic` 필요.") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY 미설정 — 이 에이전트는 실제 API 호출이 필요하다.")
        return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def investigate(self, ctx: ToolContext) -> InvestigationResult:
        client = self._client()
        lang_name = _LANG_NAMES.get(ctx.language, "the customer's native language")
        system = _SYSTEM.format(lang_name=lang_name)
        tx_id = ctx.evidence.get("tx_id", "?")

        messages = [{
            "role": "user",
            "content": ("Investigate this held transaction. Start with get_case_overview, "
                        f"then list_evidence_cards. tx_id={tx_id}."),
        }]
        result = InvestigationResult(tx_id=tx_id, submitted=None, model=self.model)

        for turn in range(1, self.max_turns + 1):
            resp = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            result.turns = turn
            result.stop_reason = resp.stop_reason

            if resp.stop_reason != "tool_use":
                break  # end_turn 등 — 종료

            # assistant 턴(생각·tool_use 블록 포함)을 그대로 히스토리에 보존
            messages.append({"role": "assistant", "content": resp.content})

            tool_results = []
            submitted_this_turn = False
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result.tool_calls.append({"turn": turn, "name": block.name,
                                          "input": dict(block.input)})
                out = ctx.run(block.name, dict(block.input))
                if block.name == "submit_investigation":
                    submitted_this_turn = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _dump(out),
                    "is_error": "error" in out,
                })
            messages.append({"role": "user", "content": tool_results})

            # submit 후에는 모델이 마무리할 한 턴만 더 돌게 두면 대개 end_turn 으로 끝난다.
            # 안전을 위해 submit 이 들어왔고 다음 응답이 또 tool_use 가 아니면 위에서 break.
            if submitted_this_turn and ctx.submitted is not None:
                # 종료 신호를 강제하지 않고 한 턴 더 준다(모델이 요약 텍스트로 end_turn).
                continue

        result.submitted = ctx.submitted
        return result


def _dump(obj: dict) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
