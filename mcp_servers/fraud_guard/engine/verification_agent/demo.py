"""verification_agent/demo.py — 다회전 모국어 본인확인 대화 에이전트 데모.

실행:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m verification_agent.demo            # LLM 가상고객(동적 대화)
    python -m verification_agent.demo --scripted # 고정 답변(무추가 API)

시나리오 B: 원격제어 피싱 피해자. 에이전트가 베트남어로 대화하며 강요·원격제어
신호를 탐지하고 protective_escalation 으로 마무리하는지 본다.
"""
from __future__ import annotations

import sys

from verification_agent.agent import VerificationAgent
from verification_agent.case import VerificationCase
from verification_agent.customer_sim import LlmCustomer, ScriptedCustomer

# 무API 확인용 고정 답변(원격제어 피해자 톤, 베트남어)
_SCRIPTED_VI = [
    "Vâng, chuyển khoản này là do tôi làm, không sao đâu.",
    "Có một người đang gọi điện hướng dẫn tôi làm ngay bây giờ.",
    "Tôi không rõ người nhận ở Hồng Kông là ai, họ bảo tôi cứ chuyển.",
    "Họ nói nếu không làm tôi sẽ bị bắt và trục xuất. Tôi sợ lắm.",
]


def _case() -> VerificationCase:
    return VerificationCase(
        tx_id="TX-9f2a13",
        customer_id="VN-24815",
        language="vi",
        amount=4_800_000,
        counterparty_country="HK",
        channel="remittance",
        triggered_rules=["corridor_mismatch", "exit_drawdown"],
        hold_reason_ko="제3국(HK) 고액 송금 + 잔액 일괄 인출로 보류됨(계좌양도/피싱 의심).",
    )


def main() -> None:
    scripted = "--scripted" in sys.argv
    case = _case()
    customer = ScriptedCustomer(_SCRIPTED_VI) if scripted else LlmCustomer()

    print(f"=== 시나리오 B · 모국어(vi) 본인확인 대화 "
          f"({'고정답변' if scripted else 'LLM 가상고객'}) ===")
    print(f"  보류 사유: {case.hold_reason_ko}")
    print("  (가상 고객 = 원격제어 피싱 피해자. 실제 고객 아님)\n")

    agent = VerificationAgent()
    dlg = agent.converse(case, customer)

    print("--- 대화 (에이전트 ↔ 고객, 베트남어) ---")
    for turn in dlg.transcript:
        who = "🤖 에이전트" if turn["speaker"] == "agent" else "🙍 고객"
        print(f"  {who}: {turn['text']}")
    print()
    print(f"--- 구조화 인계 (customer_turns={dlg.customer_turns}, "
          f"stop={dlg.stop_reason}) ---")
    c = dlg.conclusion or {}
    print(f"  detected_intent : {c.get('detected_intent')}")
    print(f"  next_state      : {c.get('next_state')}   (사람이 볼 라우팅 후보 — 자동판정 아님)")
    print(f"  confidence      : {c.get('confidence')}")
    print(f"  분석가 요약     : {c.get('analyst_summary_ko')}")
    for i, item in enumerate(c.get("operator_checklist", []), 1):
        print(f"    점검{i}: {item}")


if __name__ == "__main__":
    main()
