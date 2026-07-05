"""investigator_agent — 진짜 tool-calling 루프 기반 AI 조사 에이전트 (옵션 2).

agent/investigate.py 는 단발(single-shot) LLM 호출로 확인질문을 '한 번' 생성한다.
이 패키지는 그 대비로 **자율 tool-calling 루프**를 구현한다: Claude 가 스스로
- 어떤 증거를 더 볼지 결정하고(read-only 도구 호출),
- 룰/그룹 기준선을 조회해 근거를 확인한 뒤,
- 충분해지면 확인질문·가설·다음 점검을 제출(submit)하고 종료한다.

불변 원칙(프로젝트 헌법과 동일): **LLM 은 사기 판정자가 아니다.**
- action(allow/review/soft_block)·risk_score 는 core(결정론 코드)가 이미 확정했고,
- 이 에이전트의 도구는 전부 **read-only 근거 조회**다. 판정을 바꾸는 도구는 없다.
- 산출물은 사람(분석가)을 위한 확인질문 + 비권위(low/medium) 가설뿐이다.

core 는 이 패키지를 모른다(불변원칙 2). 여기서 core/agent 를 import 하는 단방향 의존만 둔다.
"""
from .agent import InvestigatorAgent, InvestigationResult
from .tools import ToolContext, TOOLS

__all__ = ["InvestigatorAgent", "InvestigationResult", "ToolContext", "TOOLS"]
