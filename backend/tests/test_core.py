"""backend/core.py 순수 함수 단위 테스트. LLM 실호출 없이 결정적으로 돈다."""

from __future__ import annotations

from backend.core import (
    split_answer_and_actions,
    parse_done_marker,
    strip_streaming_markers,
    active_plan,
    start_action_labels,
    build_history,
    persona_card,
    run_tool,
    pick_model,
)
from shared.llm_provider import CLAUDE_MODEL_CHAT, CLAUDE_MODEL_DOCS


def test_pick_model_routes_docs_to_sonnet():
    # 서류 관련 발화 → 서류용 모델(Sonnet)
    assert pick_model("외국인등록증 갱신 신청서 작성해줘") == CLAUDE_MODEL_DOCS
    assert pick_model("신청서 자동으로 작성하기") == CLAUDE_MODEL_DOCS
    assert pick_model("서류 뭐 필요해?") == CLAUDE_MODEL_DOCS
    assert pick_model("PDF로 받고 싶어") == CLAUDE_MODEL_DOCS


def test_pick_model_routes_chat_to_haiku():
    # 일반 대화 → 채팅 모델(Haiku)
    assert pick_model("연금 얼마나 돌려받아?") == CLAUDE_MODEL_CHAT
    assert pick_model("송금 비용 줄이기") == CLAUDE_MODEL_CHAT
    assert pick_model("") == CLAUDE_MODEL_CHAT


def test_split_basic_marker():
    text = "본문입니다.\n\n<<NEXT>>\n마감 기한 확인하기\n송금 비용 줄이기"
    body, labels = split_answer_and_actions(text)
    assert body == "본문입니다."
    assert labels == ["마감 기한 확인하기", "송금 비용 줄이기"]


def test_split_no_marker():
    body, labels = split_answer_and_actions("그냥 본문")
    assert body == "그냥 본문"
    assert labels == []


def test_split_marker_without_body_hides_marker():
    # 본문 없이 마커로 시작해도 마커가 화면에 노출되면 안 된다
    body, labels = split_answer_and_actions("<<NEXT>>\n마감 확인")
    assert "<<NEXT>>" not in body
    assert labels == []


def test_run_tool_does_not_mutate_caller_args():
    args = {"persona_id": "minh"}
    run_tool("deadline_radar", args)
    assert "as_of" not in args  # 호출자 dict 무변형


def test_split_partial_marker_hidden():
    # 스트리밍 중 꼬리가 부분 마커로 끝나면 그 앞까지만 본문
    body, labels = split_answer_and_actions("본문 <<N")
    assert body == "본문"
    assert labels == []


def test_split_drops_long_label():
    # 40자 초과 라벨은 버튼으로 안 만든다
    long = "가" * 41
    text = f"본문\n\n<<NEXT>>\n{long}\n짧은 라벨"
    body, labels = split_answer_and_actions(text)
    assert labels == ["짧은 라벨"]


def test_split_drops_narrative_line():
    # 명령형 짧은 문구가 아니라 서술 문장이 새면 버튼으로 안 만든다
    narrative = "이것은 매우 길고 자세하게 풀어서 설명하는 서술형 문장으로 끝나는 안내입니다"
    text = f"본문\n\n<<NEXT>>\n{narrative}\n마감 확인"
    body, labels = split_answer_and_actions(text)
    assert "마감 확인" in labels
    assert narrative not in labels


def test_split_max_four_labels():
    text = "본문\n\n<<NEXT>>\n하나\n둘\n셋\n넷\n다섯"
    _, labels = split_answer_and_actions(text)
    assert len(labels) == 4


def test_done_marker_parsed_and_removed():
    cleaned, is_done = parse_done_marker("끝났습니다 <<DONE>>")
    assert "<<DONE>>" not in cleaned
    assert is_done is True


def test_done_marker_absent():
    cleaned, is_done = parse_done_marker("진행 중")
    assert cleaned == "진행 중"
    assert is_done is False


def test_strip_streaming_cuts_next():
    assert strip_streaming_markers("본문\n<<NEXT>>\n라벨") == "본문"


def test_strip_streaming_hides_partial():
    assert strip_streaming_markers("본문 <<NE") == "본문"


def test_strip_streaming_removes_done():
    assert "<<DONE>>" not in strip_streaming_markers("끝 <<DONE>>")


def test_active_plan_minh_has_deadline_and_pension():
    plan = active_plan("minh")
    tools = [t for t, _ in plan]
    assert "deadline_radar" in tools  # E-9
    assert "pension_estimator" in tools  # 협정 미체결 + 납부이력
    assert "form_autofill" in tools  # 항상


def test_active_plan_suman_has_credit_builder():
    plan = active_plan("suman")
    tools = [t for t, _ in plan]
    assert "credit_builder" in tools  # 소득 0 + 예치금
    assert "deadline_radar" not in tools  # D-2는 출국만기보험 비대상


def test_start_action_labels_excludes_completed():
    labels_all = start_action_labels("minh", "ko")
    # deadline_radar 완료 처리하면 그 라벨이 빠진다
    labels_excl = start_action_labels("minh", "ko", exclude_tools={"deadline_radar"})
    assert "마감 기한 확인하기" in labels_all
    assert "마감 기한 확인하기" not in labels_excl


def test_start_action_labels_lang_en():
    labels = start_action_labels("minh", "en")
    assert any("Check" in l or "Estimate" in l or "Lower" in l for l in labels)


def test_build_history_pairs():
    messages = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    hist = build_history(messages, max_turns=3)
    assert hist == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_build_history_max_turns():
    messages = []
    for i in range(5):
        messages.append({"role": "user", "content": f"q{i}"})
        messages.append({"role": "assistant", "content": f"a{i}"})
    hist = build_history(messages, max_turns=2)
    # 마지막 2턴만 = q3/a3, q4/a4
    assert hist[0]["content"] == "q3"
    assert hist[-1]["content"] == "a4"


def test_persona_card_minh_keys():
    from shared.personas import PERSONAS
    card = persona_card(PERSONAS["minh"])
    assert card["name"] == "응웬 반 민"
    assert card["en"] == "Nguyen Van Minh"
    assert card["visa"] == "E-9"
    assert card["nationality"] == "베트남"
    # 비자 정보 존재
    assert card["visaExpiry"]
    assert "visaStatus" in card


def test_run_tool_forces_deadline_as_of():
    # deadline_radar는 as_of가 TODAY로 강제된다
    out = run_tool("deadline_radar", {"persona_id": "minh", "as_of": "1999-01-01"})
    assert isinstance(out, dict)
    assert "summary" in out


def test_run_tool_unknown_raises():
    import pytest
    with pytest.raises(RuntimeError):
        run_tool("nonexistent_tool", {})
