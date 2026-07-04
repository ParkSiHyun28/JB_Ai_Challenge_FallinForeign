"""FastAPI 엔드포인트 테스트. LLM 실호출은 monkeypatch로 차단해 결정적으로 돈다."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend import core
from backend import main as backend_main

client = TestClient(app)


def _parse_sse(raw_text):
    """SSE 텍스트를 [(event, data_str), ...] 리스트로 파싱한다."""
    events = []
    cur_event = None
    cur_data = []
    for line in raw_text.splitlines():
        if line.startswith("event:"):
            cur_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            cur_data.append(line[len("data:"):].strip())
        elif line == "":
            if cur_event is not None:
                events.append((cur_event, "\n".join(cur_data)))
            cur_event = None
            cur_data = []
    if cur_event is not None:
        events.append((cur_event, "\n".join(cur_data)))
    return events


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_personas_returns_two():
    r = client.get("/personas")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    ids = {p["id"] for p in data}
    assert ids == {"minh", "suman"}
    minh = next(p for p in data if p["id"] == "minh")
    assert minh["name"] == "응웬 반 민"
    assert minh["en"] == "Nguyen Van Minh"
    assert minh["visa"] == "E-9"
    assert minh["visaExpiry"]  # 비자 정보 존재
    assert "visaStatus" in minh


def test_intro_uses_recommend(monkeypatch):
    # LLM 호출을 막고 고정 결과를 주입한다
    def fake_recommend(persona_id, reply_lang, exclude_tools=None):
        return ("민님 상황을 살펴봤습니다.", ["마감 기한 확인하기", "송금 비용 줄이기"])

    monkeypatch.setattr(core, "ai_recommend_actions", fake_recommend)
    r = client.get("/intro?persona=minh&lang=ko")
    assert r.status_code == 200
    data = r.json()
    assert data["body"] == "민님 상황을 살펴봤습니다."
    assert data["labels"] == ["마감 기한 확인하기", "송금 비용 줄이기"]
    assert "무엇부터" in data["header"]  # START_HEADER ko


def test_intro_lang_auto_falls_back_to_ko(monkeypatch):
    captured = {}

    def fake_recommend(persona_id, reply_lang, exclude_tools=None):
        captured["lang"] = reply_lang
        return ("ok", ["a"])

    monkeypatch.setattr(core, "ai_recommend_actions", fake_recommend)
    client.get("/intro?persona=minh&lang=auto")
    assert captured["lang"] == "ko"


def test_intro_unknown_persona_falls_back(monkeypatch):
    captured = {}

    def fake_recommend(persona_id, reply_lang, exclude_tools=None):
        captured["persona"] = persona_id
        return ("ok", ["a"])

    monkeypatch.setattr(core, "ai_recommend_actions", fake_recommend)
    client.get("/intro?persona=nonexistent&lang=ko")
    assert captured["persona"] == "minh"  # 폴백


def test_intro_lang_en(monkeypatch):
    captured = {}

    def fake_recommend(persona_id, reply_lang, exclude_tools=None):
        captured["lang"] = reply_lang
        return ("ok", ["a"])

    monkeypatch.setattr(core, "ai_recommend_actions", fake_recommend)
    r = client.get("/intro?persona=suman&lang=en")
    assert captured["lang"] == "en"
    assert "help" in r.json()["header"].lower()  # START_HEADER en


def _fake_stream(user_text, system, run_tool, on_step=None, history=None):
    """가짜 run_chat_stream. on_step 1회 + 토큰 몇 개 + <<NEXT>> 라벨."""
    # tool 단계 1회 보고
    if on_step:
        on_step("tool_call", {
            "name": "remit_optimizer",
            "args": {"persona_id": "minh"},
            "output": {"summary": "송금 경로 점검 완료", "card": None},
        })
    for tok in ["송금", " 비용을", " 줄이는", " 방법입니다.", "\n\n<<NEXT>>\n", "더 알아보기"]:
        yield tok


def test_chat_sse_emits_step_token_final(monkeypatch):
    monkeypatch.setattr(backend_main, "run_chat_stream", _fake_stream)
    body = {"persona": "minh", "lang": "ko", "intent": "송금 줄이기", "is_action": True}
    with client.stream("POST", "/chat", json=body) as r:
        assert r.status_code == 200
        raw = "".join(chunk for chunk in r.iter_text())
    events = _parse_sse(raw)
    kinds = [e for e, _ in events]
    assert "step" in kinds
    assert "token" in kinds
    assert "final" in kinds
    assert kinds[-1] == "end"
    # step이 token보다 먼저(on_step이 토큰 전에 호출됨)
    assert kinds.index("step") < kinds.index("token")
    # final 본문에 마커 없음, 라벨 분리됨
    import json as _j
    final_data = _j.loads(next(d for e, d in events if e == "final"))
    assert "<<NEXT>>" not in final_data["body"]
    assert final_data["body"].strip() == "송금 비용을 줄이는 방법입니다."
    assert final_data["next_labels"] == ["더 알아보기"]
    assert final_data["is_done"] is False


def test_chat_sse_done_marker(monkeypatch):
    def fake(user_text, system, run_tool, on_step=None, history=None):
        for tok in ["끝났습니다.", " <<DONE>>"]:
            yield tok

    monkeypatch.setattr(backend_main, "run_chat_stream", fake)
    body = {"persona": "minh", "lang": "ko", "intent": "종료", "is_action": True}
    with client.stream("POST", "/chat", json=body) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    events = _parse_sse(raw)
    import json as _j
    final_data = _j.loads(next(d for e, d in events if e == "final"))
    assert final_data["is_done"] is True
    assert "<<DONE>>" not in final_data["body"]
    assert final_data["done_caption"]


def test_chat_sse_error(monkeypatch):
    def fake(user_text, system, run_tool, on_step=None, history=None):
        raise RuntimeError("ANTHROPIC_API_KEY 없음")
        yield  # 제너레이터 표시

    monkeypatch.setattr(backend_main, "run_chat_stream", fake)
    body = {"persona": "minh", "lang": "ko", "intent": "테스트", "is_action": True}
    with client.stream("POST", "/chat", json=body) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    events = _parse_sse(raw)
    kinds = [e for e, _ in events]
    assert "error" in kinds
    import json as _j
    err_data = _j.loads(next(d for e, d in events if e == "error"))
    assert "API 키" in err_data["message"]
