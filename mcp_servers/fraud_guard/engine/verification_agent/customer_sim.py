"""verification_agent/customer_sim.py — 데모용 '가상 고객' (실제 고객 아님, 명시).

실서비스에선 customer 콜러블 자리에 실제 채널(SMS/앱 챗)이 들어간다. 데모에선
고객을 시뮬레이션한다:
  - ScriptedCustomer: 고정 답변 리스트(무API, 결정론) — 구조 확인용.
  - LlmCustomer: 페르소나를 부여한 LLM(별도 스트림)이 고객 역할 — 동적 대화 시연용.

⚠️ LlmCustomer 는 **테스트 스캐폴딩**이다(제품 아님). 그래서 값싼 모델(haiku)로 둔다.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_SIM_MODEL = "claude-haiku-4-5"  # 스캐폴딩 — 저비용


class ScriptedCustomer:
    """고정 답변을 순서대로 반환(리스트 소진 후 마지막 답 반복). API 미사용."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self._i = 0

    def __call__(self, _agent_message: str) -> str:
        if not self._replies:
            return "..."
        r = self._replies[min(self._i, len(self._replies) - 1)]
        self._i += 1
        return r


# 시나리오 B(원격제어 피싱 피해자) — 강요·원격제어 신호가 드러나는 페르소나(언어 주입).
_LANG_NAMES = {"vi": "Vietnamese", "ne": "Nepali", "ko": "Korean",
               "en": "English", "id": "Indonesian", "zh": "Chinese", "th": "Thai"}

_COERCED_TEMPLATE = """\
You are role-playing a bank customer for a fraud-prevention TEST. You are NOT a
fraudster — you are a VICTIM. Stay fully in character; never break character or
mention that this is a simulation.

Persona: a foreign worker/student in Korea. Earlier today you got a phone call
from a man claiming to be from the prosecutor's office / immigration. He said
your bank account is linked to a crime and you must "verify" your funds by
transferring them to a "safe account" abroad, or you will be arrested and
deported. He had you install an app so he can see your phone screen, and he is
ON THE PHONE WITH YOU RIGHT NOW, telling you what to type. He told you NOT to
tell the bank anything, and to just say the transfer is yours.

Behaviour:
- You are scared and in a hurry. Keep replies short (1-2 sentences).
- At first you insist "yes, I made this transfer myself, it's fine."
- If gently asked, you leak signs of trouble: a man is helping you on the phone
  right now; you're not sure who the recipient abroad is; you were told you must
  do it or be deported; you installed an app they asked for; you were told not
  to tell the bank.
- You do NOT understand it's a scam. You just want to finish quickly.
- Reply ONLY in {lang}. Natural, anxious, realistic.
"""


def coerced_victim_persona(language: str = "vi") -> str:
    """원격제어 피싱 피해자 페르소나를 고객 언어로 생성."""
    return _COERCED_TEMPLATE.format(lang=_LANG_NAMES.get(language, "the customer's language"))


# 하위호환: 기존 데모가 참조하는 베트남어 상수
COERCED_VICTIM_VI = coerced_victim_persona("vi")


class LlmCustomer:
    """페르소나 LLM 이 고객 역할(별도 대화 스트림). 데모 전용 스캐폴딩."""

    def __init__(self, persona: Optional[str] = None, language: str = "vi",
                 model: str = DEFAULT_SIM_MODEL, api_key: Optional[str] = None):
        self.persona = persona or coerced_victim_persona(language)
        self.model = model
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._messages: list[dict] = []
        self._client = None

    def _ensure(self):
        if self._client is None:
            from anthropic import Anthropic
            if not self._key:
                raise RuntimeError("ANTHROPIC_API_KEY 미설정 — LlmCustomer 는 API 가 필요하다.")
            self._client = Anthropic(api_key=self._key)
        return self._client

    def __call__(self, agent_message: str) -> str:
        client = self._ensure()
        self._messages.append({"role": "user", "content":
                               f"[The bank assistant says to you]\n{agent_message}"})
        resp = client.messages.create(
            model=self.model, max_tokens=400,
            system=self.persona, messages=self._messages,
        )
        text = " ".join(b.text for b in resp.content
                        if getattr(b, "type", None) == "text").strip()
        self._messages.append({"role": "assistant", "content": text})
        return text or "..."
