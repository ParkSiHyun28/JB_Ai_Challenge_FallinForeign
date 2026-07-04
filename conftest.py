"""repo 전체 pytest 공용 설정.

AI 서식 채움(Sonnet 실호출)을 모든 테스트에서 끈다. 테스트가 결정적으로 돌고
요금이 나가지 않게 하기 위함이다. AI 경로는 스모크(tests/smoke_real_llm.py 또는
수동 실행)에서 따로 검증한다."""

import os

# pytest 수집 시점에 바로 끈다 (fixture보다 이른 시점 보장)
os.environ["DOCS_AI_FILL"] = "off"
