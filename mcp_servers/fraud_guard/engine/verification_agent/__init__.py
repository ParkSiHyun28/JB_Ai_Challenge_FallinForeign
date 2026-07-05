"""verification_agent — 고객과 모국어로 다회전 대화하는 진짜 본인확인 대화 에이전트.

기존 `agent/verification.py`(모국어 메시지 1건 생성 + 발송 mock)와
`contracts/verification_chat.py`(고객 답변 1턴 분류)를 **자율 대화 루프**로 끌어올린 것.

에이전트가:
  1) 보류된 거래에 대해 고객 모국어로 먼저 말을 걸고,
  2) 고객 답변을 듣고 **스스로 다음 질문을 이어가며**(다회전),
  3) 강요(coercion)·원격제어(remote control)·피싱 스크립트 신호를 탐지하고,
  4) 충분해지면 conclude_verification 으로 **분석가용 구조화 인계**를 만들고 종료한다.

불변 원칙(프로젝트 헌법 유지):
- 에이전트는 **승인/차단을 결정하지 않는다.** next_state 는 사람(분석가)이 볼 라우팅 후보일 뿐.
- 강요/원격제어 감지 시 "그냥 승인하라"고 말하지 않고 **보호 상신(protective escalation)** 을 만든다.
- 판정 자동화가 아니라 언어장벽 해소 + 위험신호 탐지 + 인계 요약이 역할.

enum(intent/next_state)은 contracts/verification_chat 과 값이 1:1 로 맞춰져 있다.
"""
from .agent import VerificationAgent, VerificationDialogue
from .case import VerificationCase
from .customer_sim import LlmCustomer, ScriptedCustomer

__all__ = [
    "VerificationAgent", "VerificationDialogue", "VerificationCase",
    "LlmCustomer", "ScriptedCustomer",
]
