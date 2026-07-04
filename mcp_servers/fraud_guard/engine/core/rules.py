"""core/rules.py — L1 RuleLayer (실시간, 결정론적, 설명가능).

거래 + 비자 메타데이터로 5대 룰을 평가하고 페널티를 누적한다.
푸는 것: 미탐(false negative) 방어 — 거래 로그에 없는 외부 상태(비자 만료일)를
룰로 주입한다. 룰의 '존재'는 실제 사건 패턴으로 정당화하나, 페널티 '수치'는
전부 config/rules.yaml 의 [임의] 값(라벨 후 ablation 으로 보정 예정).

mcp 의존 없음. days_to_residency_end 는 features 의 단일 함수를 재사용한다.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .config import RuleParams, load_rule_params
from .features import local_hour, residency_days_signed
from .schema import CustomerProfile, Transaction


class RuleLayer:
    def __init__(self, params: RuleParams):
        self.p = params

    @classmethod
    def from_config(cls, path: Optional[str] = None) -> "RuleLayer":
        return cls(load_rule_params(path) if path else load_rule_params())

    def evaluate(self, tx: Transaction, profile: CustomerProfile,
                 today: Optional[date] = None) -> tuple[float, list[str]]:
        """(rule_score[0~1], triggered_rules) 반환. today 주입 시 D-day 재현 가능."""
        p = self.p
        score = 0.0
        triggered: list[str] = []
        hour = local_hour(tx)  # 로컬시각(features 단일 공식) — UTC 직산 금지(P0-1)
        days_left = residency_days_signed(profile, today)  # 부호 보존(음수=만료 후), P1-5

        # (a) corridor 위반: 본국이 아닌 제3국 송금
        if tx.channel == "remittance" and tx.counterparty_country != profile.home_country:
            triggered.append("corridor_mismatch")
            score += p.penalty["corridor_mismatch"]

        # (b) 체류만료 임박 + 잔액 일괄 인출 = 계좌양도 의심
        if 0 <= days_left <= p.dday_window_days and tx.balance_drawdown_ratio >= p.exit_drawdown_min:
            triggered.append("exit_drawdown")
            score += p.penalty["exit_drawdown"]

        # (c) 신규기기 + 고액 = 계좌 탈취/양도 신호
        if tx.is_new_device and tx.amount >= p.high_amount_krw:
            triggered.append("new_device_high_amount")
            score += p.penalty["new_device_high_amount"]

        # (d) 입금 직후 즉시 전액 이체 = 인출책/통장대여·피싱 다회 인출
        if tx.tx_velocity_24h >= p.rapid_velocity_min and tx.balance_drawdown_ratio >= p.rapid_drawdown_min:
            triggered.append("rapid_passthrough")
            score += p.penalty["rapid_passthrough"]

        # (e) 야간 + 해외송금
        if hour in p.night_hours and tx.channel == "remittance":
            triggered.append("night_remittance")
            score += p.penalty["night_remittance"]

        # (f) 이미 체류만료(불법체류 의심) — '만료 후' 금융활동은 양도/대여 고위험(P1-5)
        if days_left < 0:
            triggered.append("residency_overstayed")
            score += p.penalty["residency_overstayed"]

        return min(score, 1.0), triggered
