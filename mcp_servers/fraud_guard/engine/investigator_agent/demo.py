"""investigator_agent/demo.py — 진짜 tool-calling 조사 에이전트 데모.

실행:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m investigator_agent.demo

키가 없으면: core 로 소프트블록 케이스를 만들고, 에이전트가 '무엇을' 호출하는지
도구 목록만 출력한다(실제 LLM 호출은 키가 있을 때만).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from core.pipeline import FraudGuardPipeline
from core.schema import CustomerProfile, Transaction
from investigator_agent.agent import InvestigatorAgent
from investigator_agent.tools import TOOLS, ToolContext

TODAY = date(2026, 7, 5)


def _sample_case():
    """시나리오 A(출국기 계좌양도) — 룰만으로 soft_block 되는 케이스."""
    profile = CustomerProfile(
        customer_id="VN-24815",
        nationality="VN",
        visa_type="E-9",
        residency_end_date=date(2026, 7, 12),  # D-7 (출국 임박)
        language="vi",
        home_country="VN",
    )
    ts = datetime(2026, 7, 5, 2, 30, tzinfo=timezone.utc).timestamp()  # 야간대
    tx = Transaction(
        tx_id="TX-9f2a13",
        customer_id="VN-24815",
        timestamp=ts,
        amount=4_800_000,           # 고액
        channel="remittance",
        counterparty_country="HK",  # 본국(VN) 아닌 제3국 → corridor 위반
        device_id="dev-NEW-01",
        ip_country="HK",
        balance_before=5_000_000,
        balance_drawdown_ratio=0.96,  # 잔액 일괄 인출
        is_new_device=True,           # 신규기기
        tx_velocity_24h=2,
    )
    return tx, profile


def main() -> None:
    tx, profile = _sample_case()
    pipe = FraudGuardPipeline(today=TODAY)
    result = pipe.detect_account_takeover(tx, profile)  # L1~L4 + D-day 가중

    print("=== core 결정론 판정(에이전트가 바꾸지 못함) ===")
    print(f"  action        : {result.action}")
    print(f"  risk_score    : {result.risk_score}")
    print(f"  triggered     : {result.triggered_rules}")
    print(f"  model_score   : {result.model_score}  (None=미학습 그룹, 룰축만)")
    print()

    ctx = ToolContext.from_score(tx, profile, result, today=TODAY)
    print(f"=== 에이전트에게 열린 도구 {len(TOOLS)}개 (전부 read-only + 마지막 submit) ===")
    for t in TOOLS:
        print(f"  - {t['name']}")
    print()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 미설정 → 실제 tool-calling 루프는 생략.")
        print("키를 설정하면 Claude 가 위 도구들을 스스로 호출하며 조사한다.")
        return

    print("=== 자율 tool-calling 루프 실행(Claude Opus 4.8) ===")
    agent = InvestigatorAgent()
    out = agent.investigate(ctx)

    print(f"  turns={out.turns}  stop_reason={out.stop_reason}  ok={out.ok}")
    print("  --- 도구 호출 궤적 ---")
    for c in out.tool_calls:
        arg = c["input"].get("rule_name") or ""
        print(f"    [t{c['turn']}] {c['name']} {arg}".rstrip())
    print()
    if out.submitted:
        print("  --- 제출된 조사 결과 ---")
        for q in out.submitted["verification_questions"]:
            print(f"    Q({q['purpose']}): {q['question']}  ⟵ {q['evidence_ids']}")
        for h in out.submitted.get("llm_suggested_hypotheses", []):
            print(f"    가설[{h['confidence']}]: {h['name']}  ⟵ {h['supporting_evidence_ids']}")
        print(f"    다음 점검: {out.submitted['recommended_next_check']}")
        print(f"    확신도: {out.submitted['confidence']}")


if __name__ == "__main__":
    main()
