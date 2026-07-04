"""backend 테스트 공용 설정. AI 서식 채움을 꺼서 테스트를 결정적으로 만든다.
(form_autofill을 실제 실행하는 다운로드 테스트가 Sonnet을 실호출하지 않게.)"""

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_ai_fill(monkeypatch):
    monkeypatch.setenv("DOCS_AI_FILL", "off")
