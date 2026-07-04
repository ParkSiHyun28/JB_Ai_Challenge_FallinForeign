"""Claude 전용 LLM 계층. 2모델 역할 분담.

- 채팅 응답: Haiku 4.5 (CLAUDE_MODEL_CHAT). 빠른 응답이 우선.
- 서류 작성 턴: Sonnet 4.6 (CLAUDE_MODEL_DOCS). 신청서 판단은 정확성이 우선.
  (PDF에 값을 채우는 계산 자체는 LLM 없는 결정적 코드다. 모델이 하는 일은
  어떤 서류인지 판단하고 tool을 부르고 응답 문장을 쓰는 것이다.)

턴별 모델 선택은 backend/core.py의 pick_model()이 한다. 이 파일은 모델 인자를
받아 Anthropic tool use 루프를 돌리는 호출 계층만 담당한다.

tool 정의(schemas.py)와 tool 실행(tools.py)과 시스템 프롬프트(system_prompt.py)는
모델과 무관하게 그대로 재사용한다.
"""

import os
import re
import json

from shared.registry import TOOL_SCHEMAS

# 이모지 제거용 정규식. LLM이 시스템 프롬프트 지시를 흘려 이모지를 써도 코드로 강제 제거한다.
# 산출물에 이모지를 절대 노출하지 않는다는 규칙을 출력단에서 확정한다.
_EMOJI_RE = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF" "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F" "\U000020D0-\U000020FF" "\U00002190-\U000021FF" "]+",
    flags=re.UNICODE,
)
# 한자(CJK) 제거용. 우리 도메인은 외국인 금융 상담이라 순한국어가 정상이고 한자는 누출이므로 제거한다.
# 범위는 유니코드 이스케이프로 적는다(리터럴 한자는 편집 중 깨져 한글까지 먹는 사고가 났었다).
_HANZI_RE = re.compile("[\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff]+")
# 이모지 코드포인트 제거 후 남는 ZWJ(U+200D)와 변이 선택자(U+FE0F) 잔여물 정리.
_EMOJI_JOINER_RE = re.compile("[\\u200d\\ufe0f]+")
# 모델이 같은 tool을 무한 호출하는 병적 상태 방지(한 답변 tool 2~4개면 충분, 8 여유).
MAX_TOOL_ITERATIONS = 8

# tool 호출 상한 도달 시 사용자에게 보내는 안내.
LIMIT_MESSAGE = (
    "요청을 처리하는 데 단계가 너무 많이 필요합니다. 질문을 더 구체적으로 나눠 다시 물어봐 주세요."
    "\n\n<<NEXT>>\n질문 다시 정리하기\n마감 기한 확인하기"
)


def strip_emoji(text: str) -> str:
    """텍스트에서 이모지와 한자(중국어 누출)를 제거하고 군더더기 공백을 정리한다."""
    if not text:
        return text
    out = _EMOJI_RE.sub("", text)
    out = _HANZI_RE.sub("", out)
    out = _EMOJI_JOINER_RE.sub("", out)
    # 제거 자리에 남은 연속 공백과 줄머리 공백과 빈 괄호를 정리한다.
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"^[ \t]+", "", out, flags=re.MULTILINE)
    return out


# 역할별 모델. 환경변수로 덮어쓸 수 있다.
# 채팅 응답: 속도 우선 Haiku. 서류 작성 턴: 정확성 우선 Sonnet.
CLAUDE_MODEL_CHAT = os.environ.get("CLAUDE_MODEL_CHAT", "claude-haiku-4-5")
CLAUDE_MODEL_DOCS = os.environ.get("CLAUDE_MODEL_DOCS", "claude-sonnet-4-6")


def provider_label() -> str:
    """현재 모델 구성을 사람이 읽을 라벨로 반환한다. 화면 표시용."""
    return f"Claude API (채팅 {CLAUDE_MODEL_CHAT} / 서류 {CLAUDE_MODEL_DOCS})"


def _anthropic_tools() -> list[dict]:
    """schemas.py를 Anthropic tools 형식 그대로 반환한다."""
    return list(TOOL_SCHEMAS.values())


def _client():
    """Anthropic 클라이언트를 만든다. 키가 없으면 한국어 안내로 실패한다."""
    from anthropic import Anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다. .env를 확인해 주세요.")
    return Anthropic(api_key=key)


def _run_claude(history: list[dict], system: str, run_tool, model: str) -> tuple[str, list[dict]]:
    """Anthropic tool use 루프. history는 Anthropic messages 형식을 받는다."""
    client = _client()
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    tools = _anthropic_tools()

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0,
            system=sys_blocks,
            tools=tools,
            messages=history,
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            history.append({"role": "assistant", "content": resp.content})
            return text, history
        history.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = run_tool(block.name, dict(block.input))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(out, ensure_ascii=False),
                })
        history.append({"role": "user", "content": results})
    # 상한 도달. 무한 루프 대신 안내 텍스트로 종료한다.
    return LIMIT_MESSAGE, history


def _stream_claude(history: list[dict], system: str, run_tool, model: str):
    """Anthropic tool use 루프의 스트리밍 변형. 최종 답변 텍스트를 토큰 단위로 yield한다.

    매 턴을 client.messages.stream()으로 받는다. tool_use 턴은 텍스트가 거의 없어 yield할 게
    없고, tool을 실행한 뒤 다음 턴으로 넘어간다. 마지막 텍스트 턴이 토큰 단위로 흐른다."""
    client = _client()
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    tools = _anthropic_tools()

    for _ in range(MAX_TOOL_ITERATIONS):
        with client.messages.stream(
            model=model,
            max_tokens=1500,
            temperature=0,
            system=sys_blocks,
            tools=tools,
            messages=history,
        ) as stream:
            for event in stream.text_stream:
                if event:
                    yield event  # 텍스트 델타를 즉시 흘린다.
            final = stream.get_final_message()
        if final.stop_reason != "tool_use":
            history.append({"role": "assistant", "content": final.content})
            return  # 텍스트 턴 종료. 스트리밍이 자연히 끝난다.
        history.append({"role": "assistant", "content": final.content})
        results = []
        for block in final.content:
            if block.type == "tool_use":
                out = run_tool(block.name, dict(block.input))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(out, ensure_ascii=False),
                })
        history.append({"role": "user", "content": results})
    yield "\n\n" + LIMIT_MESSAGE


def _make_traced_run_tool(run_tool, on_step):
    """run_tool을 감싸 호출 단계를 on_step으로 흘리는 래퍼를 만든다.
    tool 실행 실패 시 앱이 죽지 않도록 예외를 잡아 안전한 dict를 반환한다.
    LLM에게 오류 내용을 돌려줘 사과 답변을 생성하게 한다(예외를 다시 올리지 않음)."""
    def traced_run_tool(name, args):
        try:
            out = run_tool(name, args)
            if on_step:
                on_step("tool_call", {"name": name, "args": dict(args), "output": out})
            return out
        except Exception as e:
            if on_step:
                on_step("tool_error", {"name": name, "args": dict(args), "error": str(e)})
            return {
                "summary": f"{name} 처리 중 오류: {e}",
                "detail": "",
                "numbers": {},
                "card": None,
            }
    return traced_run_tool


def run_chat(user_text: str, system: str, run_tool, on_step=None, history=None, model=None) -> str:
    """비스트리밍 진입점. 사용자 발화 1개를 받아 최종 텍스트를 반환한다.

    user_text: 페르소나 태그가 붙은 사용자 질문.
    system: build_system_prompt() 결과.
    run_tool: (name, args) -> dict. tool 실행 함수.
    on_step: 선택. 처리 단계를 보고받는 콜백. on_step(kind, payload) 형태로 호출된다.
    history: 선택. 직전 대화 턴 [{role, content}] 리스트. 현재 발화는 포함하지 않는다.
    model: 선택. 이 턴에 쓸 Claude 모델. 없으면 채팅 기본(CLAUDE_MODEL_CHAT).
    """
    traced_run_tool = _make_traced_run_tool(run_tool, on_step)
    msgs = (list(history) if history else []) + [{"role": "user", "content": user_text}]
    text, _ = _run_claude(msgs, system, traced_run_tool, model or CLAUDE_MODEL_CHAT)
    return strip_emoji(text)


def run_chat_stream(user_text: str, system: str, run_tool, on_step=None, history=None, model=None):
    """스트리밍 진입점. 최종 답변을 토큰 단위로 yield하는 제너레이터를 반환한다.

    tool 호출 단계는 on_step으로 즉시 보고된다(run_chat과 동일 계약).
    이모지와 한자 누출은 스트림 토큰 단위로는 깨끗이 못 지우므로, 호출부에서 최종 누적
    텍스트에 strip_emoji를 한 번 더 적용한다. 여기서는 토큰을 가공 없이 흘린다.
    model: 선택. 이 턴에 쓸 Claude 모델. 없으면 채팅 기본(CLAUDE_MODEL_CHAT).
    """
    traced_run_tool = _make_traced_run_tool(run_tool, on_step)
    msgs = (list(history) if history else []) + [{"role": "user", "content": user_text}]
    yield from _stream_claude(msgs, system, traced_run_tool, model or CLAUDE_MODEL_CHAT)
