"""agent/verification.py — L4 모국어 본인확인 (request_verification 의 두뇌).

보류(soft_block)된 의심 거래에 대해 고객 '모국어'로 본인확인 메시지를 만든다.
외국인 특화 차별점: 시나리오 B(모국어 피싱)는 한국어 안내로는 효과가 낮으므로
고객 모국어로 "이 거래 본인 맞습니까?"를 묻는다. 실시간 결제망 밖(비동기 L4).

mode="template"(기본): 결정론적 템플릿 → 무설치·테스트 가능.
mode="claude":  anthropic + ANTHROPIC_API_KEY → Claude 로 더 자연스럽게 생성. 실패 시 템플릿 폴백.
mode="openai":  OpenAI 호환 chat API 로 무료 LLM(Groq·Gemini·Ollama·OpenRouter 등) 사용.
                stdlib(urllib)만 — 추가 설치 불필요. 실패 시 템플릿 폴백.
                env: FRAUDGUARD_LLM_BASE_URL / FRAUDGUARD_LLM_API_KEY / FRAUDGUARD_LLM_MODEL.
(core 와 무관, mcp 의존 없음)
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from core.schema import CustomerProfile, ScoreResult, Transaction

# 모국어 본인확인 템플릿 (스텁). 실제 운영은 mode="claude" 권장.
_TEMPLATES = {
    "vi": ("Xin chào, chúng tôi tạm giữ một giao dịch bất thường trên tài khoản của bạn: "
           "{amount:,.0f} KRW đến {country} ({channel}). Bạn có thực hiện giao dịch này không? "
           "Vui lòng xác nhận."),
    "ne": ("नमस्ते, तपाईंको खातामा एउटा असामान्य कारोबार अस्थायी रूपमा रोकिएको छ: "
           "{country} मा {amount:,.0f} KRW ({channel})। के यो कारोबार तपाईं आफैले गर्नुभएको हो? "
           "कृपया पुष्टि गर्नुहोस्।"),
    "ko": ("고객님 계좌에서 이상 거래가 감지되어 잠시 보류했습니다: {country}(으)로 "
           "{amount:,.0f} KRW ({channel}). 본인이 요청하신 거래가 맞습니까? 확인 부탁드립니다."),
    "en": ("We have temporarily held an unusual transaction on your account: {amount:,.0f} KRW "
           "to {country} ({channel}). Did you authorize this? Please confirm."),
}

# LLM 프롬프트용 언어명. 코드(ne)만 주면 약한 모델이 오언어로 답하므로 이름+스크립트를 명시한다.
_LANG_NAMES = {
    "vi": "Vietnamese (Tiếng Việt)",
    "ne": "Nepali (नेपाली, Devanagari script)",
    "ko": "Korean (한국어)",
    "en": "English",
}


def _reason(result: Optional[ScoreResult]) -> str:
    if result is None:
        return "unusual_pattern"
    if result.triggered_rules:
        return ", ".join(result.triggered_rules)
    axes = (result.explanation or {}).get("axes", {})
    if axes.get("model_pctl") is not None:
        return f"model_anomaly(pctl={axes['model_pctl']})"
    return "unusual_pattern"


class Verifier:
    def __init__(self, mode: str = "template", model: str = "claude-sonnet-4-20250514"):
        self.mode = mode
        self.model = model

    def _template_message(self, tx: Transaction, profile: CustomerProfile) -> str:
        tmpl = _TEMPLATES.get(profile.language, _TEMPLATES["en"])
        return tmpl.format(amount=tx.amount, country=tx.counterparty_country, channel=tx.channel)

    def _prompt(self, tx: Transaction, profile: CustomerProfile, reason: str) -> str:
        """claude·openai 공용 프롬프트 — 고객 모국어로 짧고 정중한 확인요청만 생성하도록 지시.
        언어 코드만 주면 약한 모델이 엉뚱한 언어로 답하므로 언어명+스크립트를 명시한다."""
        lang = _LANG_NAMES.get(profile.language, profile.language)
        return (
            f"Write your entire reply ONLY in {lang}. Use no other language or script.\n"
            f"A bank transaction was temporarily held for a security review. Customer-facing "
            f"details — amount: {tx.amount:,.0f} KRW, destination country: "
            f"{tx.counterparty_country}, channel: {tx.channel}.\n"
            f"(Internal context, do NOT quote to the customer: trigger={reason}.)\n"
            f"Write a short, polite message telling the customer we held this transaction for "
            f"security and asking them to confirm whether they made it. Do not include any "
            f"internal codes or technical jargon. Output only that message in {lang} — "
            f"no preamble, no translation, no notes."
        )

    def _claude_message(self, tx: Transaction, profile: CustomerProfile, reason: str) -> Optional[str]:
        try:  # anthropic 미설치/키 없음/오류 시 None → 템플릿 폴백
            from anthropic import Anthropic
            client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model=self.model, max_tokens=300,
                messages=[{"role": "user", "content": self._prompt(tx, profile, reason)}],
            )
            return msg.content[0].text.strip()
        except Exception:
            return None

    def _openai_message(self, tx: Transaction, profile: CustomerProfile, reason: str) -> Optional[str]:
        """OpenAI 호환 chat completions 로 생성(무료 LLM 테스트). 실패 시 None→템플릿 폴백.
        stdlib(urllib)만 사용 → openai SDK 설치 불필요. 어떤 OpenAI 호환 엔드포인트든 동작:
          Groq   BASE_URL=https://api.groq.com/openai/v1                            MODEL=llama-3.3-70b-versatile
          Gemini BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai   MODEL=gemini-2.0-flash
          Ollama BASE_URL=http://localhost:11434/v1  (API_KEY 불필요)               MODEL=qwen2.5
        """
        base_url = os.environ.get("FRAUDGUARD_LLM_BASE_URL")
        if not base_url:
            return None  # 미설정 → 폴백(테스트 안전)
        api_key = os.environ.get("FRAUDGUARD_LLM_API_KEY", "not-needed")  # Ollama 는 더미 키 허용
        model = os.environ.get("FRAUDGUARD_LLM_MODEL", self.model)
        payload = json.dumps({
            "model": model, "max_tokens": 300,
            "messages": [{"role": "user", "content": self._prompt(tx, profile, reason)}],
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions", data=payload, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                     # 일부 게이트웨이(예: Cloudflare 앞단의 Groq)는 기본 urllib UA 를 봇으로 차단(403/1010).
                     "User-Agent": "fraud-guard/1.0"},
        )
        try:  # 네트워크/키/모델 오류 시 None → 템플릿 폴백
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = (data["choices"][0]["message"]["content"] or "").strip()
            return text or None
        except Exception:
            return None

    def request(self, tx: Transaction, profile: CustomerProfile,
                result: Optional[ScoreResult] = None) -> dict:
        """보류 거래 → 모국어 본인확인 케이스(dict). 실제 발송/응답수집은 오케스트레이터 몫."""
        reason = _reason(result)
        message, generated_by = None, "template"
        if self.mode == "claude":
            message = self._claude_message(tx, profile, reason)
            generated_by = "claude" if message else "template"
        elif self.mode == "openai":
            message = self._openai_message(tx, profile, reason)
            generated_by = "openai" if message else "template"
        if message is None:
            message = self._template_message(tx, profile)
        return {
            "tx_id": tx.tx_id,
            "customer_id": profile.customer_id,
            "language": profile.language,
            "channel": "native_language_verification",
            "reason": reason,
            "message": message,
            "status": "awaiting_customer_confirmation",
            "generated_by": generated_by,
        }
