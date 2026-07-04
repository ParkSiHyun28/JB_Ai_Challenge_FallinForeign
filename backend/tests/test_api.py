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


def test_intro_unknown_persona_returns_400():
    # 알 수 없는 페르소나를 조용히 다른 사람으로 바꾸지 않는다. 400으로 드러낸다.
    r = client.get("/intro?persona=nonexistent&lang=ko")
    assert r.status_code == 400


def test_chat_unknown_persona_returns_400():
    body = {"persona": "nonexistent", "lang": "ko", "intent": "테스트", "is_action": True}
    r = client.post("/chat", json=body)
    assert r.status_code == 400


def test_intro_lang_en(monkeypatch):
    captured = {}

    def fake_recommend(persona_id, reply_lang, exclude_tools=None):
        captured["lang"] = reply_lang
        return ("ok", ["a"])

    monkeypatch.setattr(core, "ai_recommend_actions", fake_recommend)
    r = client.get("/intro?persona=suman&lang=en")
    assert captured["lang"] == "en"
    assert "help" in r.json()["header"].lower()  # START_HEADER en


def _fake_stream(user_text, system, run_tool, on_step=None, history=None, model=None):
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
    def fake(user_text, system, run_tool, on_step=None, history=None, model=None):
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
    def fake(user_text, system, run_tool, on_step=None, history=None, model=None):
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


# ---------------------------------------------------------------------------
# 신청서 PDF 다운로드
# ---------------------------------------------------------------------------

def test_attach_download_adds_url_without_mutating_original():
    card = {"icon": "", "head": "h", "body": "b", "metric": "m"}
    numbers = {"output_pdf_path": "/tmp/any/minh_pension_return_claim_filled.pdf"}
    out = core.attach_download(card, numbers)
    assert out["download_url"] == "/download/minh_pension_return_claim_filled.pdf"
    assert "download_url" not in card  # 원본 비변형


def test_attach_download_passthrough_when_no_pdf():
    card = {"icon": "", "head": "h", "body": "b", "metric": "m"}
    assert core.attach_download(card, {}) is card
    assert core.attach_download(None, {"output_pdf_path": "/tmp/x.pdf"}) is None


def test_download_filename_korean():
    assert core.download_filename("minh_pension_return_claim_filled.pdf") == "국민연금 반환일시금 신청서.pdf"
    assert core.download_filename("unknown.pdf") == "unknown.pdf"


def test_download_rejects_bad_filename():
    assert client.get("/download/evil.txt").status_code == 400
    assert client.get("/download/..%2Fsecret.pdf").status_code in (400, 404)


def test_download_404_when_missing():
    r = client.get("/download/nobody_nonexistent_form_filled.pdf")
    assert r.status_code == 404


def test_download_serves_generated_pdf():
    # 실제로 신청서를 생성한 뒤 그 파일을 내려받는다 (전 구간 검증)
    result = core.run_tool("form_autofill", {"persona_id": "minh", "form_id": "pension_return_claim"})
    import os as _os
    fname = _os.path.basename(result["numbers"]["output_pdf_path"])
    r = client.get(f"/download/{fname}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    # 받는 사람용 한글 파일명 (RFC 5987 filename*)
    assert "content-disposition" in r.headers
    assert "attachment" in r.headers["content-disposition"]


def test_chat_step_card_carries_download_url(monkeypatch):
    """form_autofill을 부르는 가짜 스트림에서 step 카드에 download_url이 실리는지."""
    def fake(user_text, system, run_tool, on_step=None, history=None, model=None):
        if on_step:
            out = run_tool("form_autofill", {"persona_id": "minh", "form_id": "pension_return_claim"})
            on_step("tool_call", {"name": "form_autofill", "args": {}, "output": out})
        yield "신청서를 작성했습니다."

    monkeypatch.setattr(backend_main, "run_chat_stream", fake)
    body = {"persona": "minh", "lang": "ko", "intent": "신청서 작성", "is_action": True}
    with client.stream("POST", "/chat", json=body) as r:
        raw = "".join(chunk for chunk in r.iter_text())
    events = _parse_sse(raw)
    import json as _j
    step_data = _j.loads(next(d for e, d in events if e == "step"))
    assert step_data["card"]["download_url"] == "/download/minh_pension_return_claim_filled.pdf"
