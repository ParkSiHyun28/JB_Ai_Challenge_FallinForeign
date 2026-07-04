"""docs 테스트 공용 설정. AI 서식 채움을 꺼서 테스트를 결정적으로 만든다.
AI 경로(Sonnet 실호출)는 tests/smoke_real_llm.py 스모크에서 따로 검증한다."""

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_ai_fill(monkeypatch):
    monkeypatch.setenv("DOCS_AI_FILL", "off")
