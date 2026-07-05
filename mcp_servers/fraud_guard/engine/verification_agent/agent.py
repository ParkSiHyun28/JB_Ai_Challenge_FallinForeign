"""verification_agent/agent.py — 다회전 모국어 본인확인 대화 에이전트 (핵심).

대화 루프(agent ↔ 고객):
  - 에이전트가 고객 모국어로 메시지를 낸다(assistant text = 고객에게 보낼 말).
  - 외부 `customer` 콜러블이 고객 답변을 돌려준다(실서비스=채널, 데모=시뮬레이션).
  - 에이전트가 답변을 듣고 스스로 다음 질문을 이어가거나, 충분하면
    conclude_verification(도구)를 호출해 구조화 인계를 만들고 종료한다.

Anthropic 규약(claude-api): model=claude-opus-4-8, thinking=adaptive, manual loop.
  - stop_reason=="tool_use"  → conclude_verification 실행 후 종료
  - stop_reason=="end_turn"  → 그 텍스트를 고객에게 전달하고 답변을 받아 루프 지속

원칙: 에이전트는 승인/차단을 결정하지 않는다. 강요/원격제어 감지 시 보호상신을 만든다.
anthropic 미설치/키 없음이면 명확히 예외(조용한 폴백 없음).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from .case import CONCLUDE_TOOL, VerificationCase

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 3000
MAX_CUSTOMER_TURNS = 6  # 고객 왕복 상한(대화가 늘어지지 않게)

# customer(agent_message) -> customer_reply  (실서비스=채널, 데모=시뮬레이터)
CustomerFn = Callable[[str], str]

_LANG_NAMES = {
    "ko": "Korean (한국어)", "vi": "Vietnamese (Tiếng Việt)",
    "ne": "Nepali (नेपाली, Devanagari script)", "en": "English",
    "id": "Indonesian", "zh": "Chinese", "th": "Thai",
}

_SYSTEM = """\
You are a bank fraud-prevention assistant speaking DIRECTLY to a foreign bank
customer, in their native language ({lang_name}), about a transaction the bank
has temporarily held for a security check.

Your goals, in order:
1. Reassure the customer briefly, then confirm whether THEY themselves
   authorized this transaction.
2. Watch for danger signals and probe gently if you see any:
   - coercion: someone is pressuring or threatening them to send money.
   - remote control: someone else is operating their phone/PC, or they were
     told to install an app that lets a stranger see their screen.
   - scam script: they are repeating instructions from a caller who claims to
     be police / immigration / a bank / a prosecutor.
3. When you have enough signal, call conclude_verification ONCE and stop.

Hard rules:
- You do NOT approve or block the transaction. A human analyst decides.
  Your output is a structured handoff, not a verdict.
- If you detect coercion or remote control, DO NOT tell the customer to
  "just approve it" or reassure them the transfer is fine. Their safety comes
  first: keep them calm, gently suggest they pause, and set
  next_state = protective_escalation.
- Speak ONLY in {lang_name}. One short, warm question at a time — do not
  interrogate, do not dump a list of questions.
- Never reveal internal fraud rules, scores, or that specific "rules fired".
- Keep it to a few turns. Every message you write (that is not a tool call)
  is sent verbatim to the customer, so write it as a real chat message.

Case facts (context for you; do NOT read rule names aloud to the customer):
{facts}
"""


@dataclass
class VerificationDialogue:
    """대화 1회 실행 결과 — 트랜스크립트 + 구조화 인계 + 루프 관측치."""

    tx_id: str
    transcript: list[dict] = field(default_factory=list)  # [{speaker, text}]
    conclusion: Optional[dict] = None
    customer_turns: int = 0
    stop_reason: Optional[str] = None
    model: str = DEFAULT_MODEL

    @property
    def ok(self) -> bool:
        return self.conclusion is not None


class VerificationAgent:
    def __init__(self, model: str = DEFAULT_MODEL, max_customer_turns: int = MAX_CUSTOMER_TURNS):
        self.model = model
        self.max_customer_turns = max_customer_turns

    def _client(self):
        try:
            from anthropic import Anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("실제 대화 에이전트다 — `pip install anthropic` 필요.") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY 미설정 — 실제 API 호출이 필요하다.")
        return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def converse(self, case: VerificationCase, customer: CustomerFn) -> VerificationDialogue:
        import json

        client = self._client()
        lang_name = _LANG_NAMES.get(case.language, "the customer's native language")
        system = _SYSTEM.format(
            lang_name=lang_name,
            facts=json.dumps(case.facts_for_prompt(), ensure_ascii=False),
        )
        messages = [{"role": "user", "content":
                     "Begin the verification chat now. Send your opening message to the customer."}]
        dlg = VerificationDialogue(tx_id=case.tx_id, model=self.model)

        # 전체 왕복 상한: 고객 턴 + 도구/마무리 여유
        for _ in range(self.max_customer_turns * 2 + 4):
            resp = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=system,
                tools=[CONCLUDE_TOOL],
                messages=messages,
            )
            dlg.stop_reason = resp.stop_reason

            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                # 마무리 도구 앞에 고객용 텍스트가 함께 오면 트랜스크립트에 남긴다
                pre_text = _text_of(resp)
                if pre_text:
                    dlg.transcript.append({"speaker": "agent", "text": pre_text})
                tool_results = []
                concluded = False
                for block in resp.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    out = case.run(block.name, dict(block.input))
                    if block.name == "conclude_verification":
                        concluded = True
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": json.dumps(out, ensure_ascii=False),
                                         "is_error": "error" in out})
                messages.append({"role": "user", "content": tool_results})
                if concluded:
                    dlg.conclusion = case.concluded
                    closing = (case.concluded or {}).get("closing_message_native")
                    if closing:
                        dlg.transcript.append({"speaker": "agent", "text": closing})
                    break
                continue

            # end_turn: assistant 텍스트 = 고객에게 보낼 말
            agent_msg = _text_of(resp)
            if not agent_msg:
                break
            dlg.transcript.append({"speaker": "agent", "text": agent_msg})

            if dlg.customer_turns >= self.max_customer_turns:
                # 예산 소진 — 고객에게 더 안 묻고, 모델에게 마무리(conclude)를 유도
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content":
                                 "You have reached the conversation limit. "
                                 "Call conclude_verification now based on what you have."})
                continue

            reply = customer(agent_msg)
            dlg.customer_turns += 1
            dlg.transcript.append({"speaker": "customer", "text": reply})
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content":
                             f"[Customer reply, in their own words]\n{reply}"})

        return dlg


def _text_of(resp) -> str:
    return " ".join(b.text for b in resp.content
                    if getattr(b, "type", None) == "text").strip()
