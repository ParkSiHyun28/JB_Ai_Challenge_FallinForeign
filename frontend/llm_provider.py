"""LLM 공급자 스위치.
환경변수 LLM_PROVIDER로 ollama(무료 로컬)와 claude(API)를 분기한다.

- 시연: LLM_PROVIDER=ollama. Ollama 로컬 모델(qwen3.5:4b)로 무료 구동. API 키 불필요.
- 본선: LLM_PROVIDER=claude. 실제 ANTHROPIC_API_KEY로 고성능 모델 구동.

tool 정의(schemas.py)와 tool 실행(tools.py)과 시스템 프롬프트(system_prompt.py)는
공급자와 무관하게 그대로 재사용한다. 이 파일은 공급자별 호출 형식 차이만 흡수한다.
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
# 한자(CJK) 제거용. 로컬 모델이 가끔 중국어를 섞는다(벤치에서 qwen3.5:4b 한자 1회 누출 관측).
# 우리 도메인은 외국인 금융 상담이라 순한국어가 정상이고 한자는 누출이므로 제거한다.
# (아래 _HANZI_RE 다음 줄에 ZWJ 정리 정규식과 tool 루프 상한을 둔다.)
# _EMOJI_JOINER_RE: 이모지 코드포인트 제거 후 남는 ZWJ(U+200D)와 변이 선택자(U+FE0F) 잔여물 정리.
# MAX_TOOL_ITERATIONS: 모델이 같은 tool을 무한 호출하는 병적 상태 방지(한 답변 tool 2~4개면 충분, 8 여유).
_HANZI_RE = re.compile("[㐀-䶿一-鿿豈-﫿]+")
_EMOJI_JOINER_RE = re.compile("[\u200d\ufe0f]+")
MAX_TOOL_ITERATIONS = 8


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

# 공급자 설정. 기본은 무료 클라우드 Gemini.
# 배포(Streamlit Cloud)에는 로컬 ollama 서버가 없으므로 ollama를 기본으로 두면 첫 요청이 깨진다.
# 로컬에서 ollama를 쓰려면 .env에 LLM_PROVIDER=ollama로 덮어쓴다.
PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

# claude 경로 설정. 배포는 Secrets에서 claude로 오버라이드됨.
# 기본값은 로컬 무키 환경 폴백용이므로 응답 속도가 빠른 haiku를 씀.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")

# ollama 경로 설정. Ollama는 OpenAI 호환 엔드포인트를 제공한다.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")

# gemini 경로 설정. 무료 티어. OpenAI 호환 엔드포인트를 제공한다.
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# groq 경로 설정. 무료 티어. OpenAI 호환 엔드포인트를 제공한다. LPU 가속으로 매우 빠르다.
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# OpenAI 호환 공급자 표. base_url/모델/키 환경변수만 다르고 호출 로직은 같다.
# ollama는 키 검증이 없어 더미 키를 쓴다.
_OPENAI_COMPAT = {
    "ollama": {"base_url": OLLAMA_BASE_URL, "model": OLLAMA_MODEL, "key_env": None, "no_think": True, "tool_retry": 0},
    "gemini": {"base_url": GEMINI_BASE_URL, "model": GEMINI_MODEL, "key_env": "GEMINI_API_KEY", "no_think": False, "tool_retry": 0},
    # groq의 Llama 3.3 70B는 긴 한국어 시스템 프롬프트에서 가끔 tool call을 <function=...> XML로
    # 잘못 뱉어 400(tool_use_failed)이 난다. 알려진 간헐 버그라 같은 입력도 재시도하면 대개 통과한다.
    "groq": {"base_url": GROQ_BASE_URL, "model": GROQ_MODEL, "key_env": "GROQ_API_KEY", "no_think": False, "tool_retry": 3},
}


def provider_label() -> str:
    """현재 공급자와 모델을 사람이 읽을 라벨로 반환한다. 사이드바 표시용."""
    if PROVIDER == "claude":
        return f"Claude API ({CLAUDE_MODEL})"
    if PROVIDER == "gemini":
        return f"Gemini 무료 ({GEMINI_MODEL})"
    if PROVIDER == "groq":
        return f"Groq 무료 ({GROQ_MODEL})"
    return f"Ollama 로컬 ({OLLAMA_MODEL})"


def _anthropic_tools() -> list[dict]:
    """schemas.py를 Anthropic tools 형식 그대로 반환한다."""
    return list(TOOL_SCHEMAS.values())


def _openai_tools() -> list[dict]:
    """schemas.py를 OpenAI function-calling 형식으로 변환한다.
    Anthropic {name, description, input_schema} → OpenAI {type, function:{name, description, parameters}}."""
    out = []
    for s in TOOL_SCHEMAS.values():
        out.append({
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        })
    return out


# --- Claude 경로 ---

def _run_claude(history: list[dict], system: str, run_tool) -> tuple[str, list[dict]]:
    """Anthropic tool use 루프. history는 Anthropic messages 형식을 받는다."""
    from anthropic import Anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("LLM_PROVIDER=claude인데 ANTHROPIC_API_KEY가 없습니다.")
    client = Anthropic(api_key=key)
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    tools = _anthropic_tools()

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
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
    return (
        "요청을 처리하는 데 단계가 너무 많이 필요합니다. 질문을 더 구체적으로 나눠 다시 물어봐 주세요."
        "\n\n<<NEXT>>\n질문 다시 정리하기\n마감 기한 확인하기",
        history,
    )


def _stream_claude(history: list[dict], system: str, run_tool):
    """Anthropic tool use 루프의 스트리밍 변형. 최종 답변 텍스트를 토큰 단위로 yield한다.

    매 턴을 client.messages.stream()으로 받는다. tool_use 턴은 텍스트가 거의 없어 yield할 게
    없고, tool을 실행한 뒤 다음 턴으로 넘어간다. 마지막 텍스트 턴이 토큰 단위로 흐른다.
    OpenAI 호환 경로와 달리 Claude는 실제로 토큰이 조각조각 도착해 스트리밍 효과가 난다."""
    from anthropic import Anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("LLM_PROVIDER=claude인데 ANTHROPIC_API_KEY가 없습니다.")
    client = Anthropic(api_key=key)
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    tools = _anthropic_tools()

    for _ in range(MAX_TOOL_ITERATIONS):
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=1500,
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
    yield "\n\n요청을 처리하는 데 단계가 너무 많이 필요합니다. 질문을 더 구체적으로 나눠 다시 물어봐 주세요.\n\n<<NEXT>>\n질문 다시 정리하기\n마감 기한 확인하기"


# --- OpenAI 호환 경로 (ollama / gemini / groq 공용) ---

def _run_openai_compat(cfg: dict, history: list[dict], system: str, run_tool) -> tuple[str, list[dict]]:
    """OpenAI 호환 tool calling 루프. ollama/gemini/groq가 같은 로직을 공유한다.
    cfg는 _OPENAI_COMPAT의 한 항목(base_url/model/key_env/no_think).
    history는 OpenAI messages 형식을 받는다(첫 호출 시 user 메시지 1개)."""
    from openai import OpenAI

    key_env = cfg["key_env"]
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise RuntimeError(f"LLM_PROVIDER={PROVIDER}인데 {key_env}가 없습니다.")
    else:
        key = "ollama"  # 로컬은 키 검증 없음
    client = OpenAI(base_url=cfg["base_url"], api_key=key)
    tools = _openai_tools()
    # qwen3 등 로컬 모델은 thinking 모드가 기본이라 추론 토큰으로 크게 느려진다.
    # /no_think로 추론을 꺼 속도를 확보한다. 클라우드 모델(gemini/groq)은 불필요.
    sys_text = system + ("\n\n/no_think" if cfg["no_think"] else "")
    # groq Llama는 tool call을 XML로 잘못 뱉는 버릇이 있어 표준 JSON 형식을 명시한다.
    if cfg.get("tool_retry"):
        sys_text += "\n\ntool을 호출할 때는 반드시 표준 JSON tool_call 형식만 쓴다. <function=...> 같은 텍스트 형식은 금지한다."
    messages = [{"role": "system", "content": sys_text}] + history

    def _create():
        """tool_use_failed(groq 간헐 400)면 재시도한다. 다른 오류는 그대로 올린다.
        ollama(key_env None)일 때 연결 실패는 친절한 안내 메시지로 변환해 올린다."""
        from openai import BadRequestError
        last = None
        for _ in range(cfg.get("tool_retry", 0) + 1):
            try:
                return client.chat.completions.create(
                    model=cfg["model"], messages=messages, tools=tools,
                    max_tokens=1500,  # 4b 폭주(4천 토큰 장황 생성) 방지. 요약 답변엔 충분.
                )
            except BadRequestError as e:
                if "tool_use_failed" not in str(e):
                    raise
                last = e  # 간헐 버그. 다시 시도.
            except (ConnectionError, OSError) as e:
                # ollama는 로컬 서버가 없으면 연결 거부(ConnectionRefusedError/OSError)가 난다.
                # Streamlit Cloud처럼 로컬 Ollama를 띄울 수 없는 환경에서 명확한 안내를 준다.
                if cfg.get("key_env") is None:
                    raise RuntimeError(
                        "LLM_PROVIDER=ollama는 로컬 Ollama 서버(localhost:11434)가 필요합니다. "
                        "Streamlit Cloud에선 LLM_PROVIDER=gemini로 설정하고 "
                        "GEMINI_API_KEY를 Secrets에 넣으세요."
                    ) from e
                raise
        raise last

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = _create()
        msg = resp.choices[0].message
        if not msg.tool_calls:
            text = msg.content or ""
            messages.append({"role": "assistant", "content": text})
            return text, messages
        # assistant turn에 tool_calls 보존
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            # 모델이 깨진 JSON 인자를 뱉으면 빈 인자로 폴백
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}
            out = run_tool(tc.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(out, ensure_ascii=False),
            })
    # 상한 도달. 무한 루프 대신 안내 텍스트로 종료한다.
    return (
        "요청을 처리하는 데 단계가 너무 많이 필요합니다. 질문을 더 구체적으로 나눠 다시 물어봐 주세요."
        "\n\n<<NEXT>>\n질문 다시 정리하기\n마감 기한 확인하기",
        messages,
    )


def run_chat(user_text: str, system: str, run_tool, on_step=None, history=None) -> str:
    """공급자 무관 진입점. 사용자 발화 1개를 받아 최종 텍스트를 반환한다.

    user_text: 페르소나 태그가 붙은 사용자 질문.
    system: build_system_prompt() 결과.
    run_tool: (name, args) -> dict. app.py가 넘기는 tool 실행 함수.
    on_step: 선택. 처리 단계를 보고받는 콜백. on_step(kind, payload) 형태로 호출된다.
             kind="tool_call"이면 payload={name, args, output}. 시각화 패널이 이걸 받는다.
    history: 선택. 직전 대화 턴 [{role, content}] 리스트. 멀티턴 메모리용(하위 호환).
             텍스트 user/assistant 메시지만 포함한다(tool_result 블록 제외).
             현재 발화(user_text)는 여기에 포함하지 않는다(함수 내부에서 추가됨).
    """
    # run_tool을 감싸 호출 단계를 on_step으로 흘린다. 실제 동작과 100% 일치한다.
    # tool 실행 실패 시 앱이 죽지 않도록 예외를 잡아 안전한 dict를 반환한다.
    def traced_run_tool(name, args):
        try:
            out = run_tool(name, args)
            if on_step:
                on_step("tool_call", {"name": name, "args": dict(args), "output": out})
            return out
        except Exception as e:
            if on_step:
                on_step("tool_error", {"name": name, "args": dict(args), "error": str(e)})
            # LLM에게 오류 내용을 돌려줘 사과 답변을 생성하게 한다. 예외를 다시 올리지 않는다.
            return {
                "summary": f"{name} 처리 중 오류: {e}",
                "detail": "",
                "numbers": {},
                "card": None,
            }

    # 멀티턴 메모리: 이전 대화 턴이 있으면 앞에 붙이고 현재 발화를 마지막에 추가한다.
    prior = list(history) if history else []
    cur_msg = {"role": "user", "content": user_text}

    if PROVIDER == "claude":
        msgs = prior + [cur_msg]
        text, _ = _run_claude(msgs, system, traced_run_tool)
        return strip_emoji(text)
    cfg = _OPENAI_COMPAT.get(PROVIDER)
    if cfg is None:
        raise RuntimeError(
            f"알 수 없는 LLM_PROVIDER={PROVIDER}. 가능: claude, ollama, gemini, groq."
        )
    msgs = prior + [cur_msg]
    text, _ = _run_openai_compat(cfg, msgs, system, traced_run_tool)
    return strip_emoji(text)


# --- 스트리밍 경로 (OpenAI 호환 공급자 전용) ---

def _stream_openai_compat(cfg: dict, history: list[dict], system: str, run_tool):
    """OpenAI 호환 tool calling 루프의 스트리밍 변형. 최종 답변 토큰을 yield한다.

    동작: 매 assistant 턴을 stream=True로 받는다. delta.content는 즉시 yield하고
    delta.tool_calls는 버퍼에 모은다. 턴이 끝났을 때 tool_calls가 있으면 tool을 실행하고
    다음 턴으로 넘어간다(이 턴의 content는 보통 비어 있어 yield할 것이 없다).
    tool_calls가 없으면 그 턴의 content가 최종 답변이므로 스트리밍이 자연히 끝난다.

    tool 결정 턴은 content가 거의 없어 사용자에겐 마지막 답변만 흐르는 것처럼 보인다.
    groq의 tool_use_failed 재시도(비스트리밍)는 스트리밍에선 적용하지 않는다. groq는
    스트리밍 대상이 아니라 기본 공급자 gemini를 전제로 한다."""
    from openai import OpenAI

    key_env = cfg["key_env"]
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise RuntimeError(f"LLM_PROVIDER={PROVIDER}인데 {key_env}가 없습니다.")
    else:
        key = "ollama"
    client = OpenAI(base_url=cfg["base_url"], api_key=key)
    tools = _openai_tools()
    sys_text = system + ("\n\n/no_think" if cfg["no_think"] else "")
    messages = [{"role": "system", "content": sys_text}] + history

    for _ in range(MAX_TOOL_ITERATIONS):
        stream = client.chat.completions.create(
            model=cfg["model"], messages=messages, tools=tools,
            max_tokens=1500, stream=True,
        )
        content_parts = []
        # tool_calls 조립용. 스트리밍은 index별로 조각이 나뉘어 온다.
        tool_acc = {}  # index -> {"id", "name", "args"}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                yield delta.content  # 최종 답변 토큰을 즉시 흘린다.
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments

        if not tool_acc:
            return  # tool 호출 없음. 흐른 content가 최종 답변이다.

        # tool 호출 턴 보존 후 실행
        messages.append({
            "role": "assistant",
            "content": "".join(content_parts) or "",
            "tool_calls": [
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["args"]},
                }
                for slot in tool_acc.values()
            ],
        })
        for slot in tool_acc.values():
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {}
            out = run_tool(slot["name"], args)
            messages.append({
                "role": "tool",
                "tool_call_id": slot["id"],
                "content": json.dumps(out, ensure_ascii=False),
            })
    yield "\n\n요청을 처리하는 데 단계가 너무 많이 필요합니다. 질문을 더 구체적으로 나눠 다시 물어봐 주세요.\n\n<<NEXT>>\n질문 다시 정리하기\n마감 기한 확인하기"


def run_chat_stream(user_text: str, system: str, run_tool, on_step=None, history=None):
    """스트리밍 진입점. 최종 답변을 토큰 단위로 yield하는 제너레이터를 반환한다.

    claude는 네이티브 토큰 스트리밍(_stream_claude)으로 글자가 흐른다.
    OpenAI 호환 공급자(gemini/groq/ollama)는 _stream_openai_compat으로 흐른다.
    tool 호출 단계는 on_step으로 즉시 보고된다(run_chat과 동일 계약).
    이모지와 한자 누출은 스트림 토큰 단위로는 깨끗이 못 지우므로, app 쪽에서 최종 누적 텍스트에
    strip_emoji를 한 번 더 적용하도록 한다. 여기서는 토큰을 가공 없이 흘린다.
    history: 선택. 직전 대화 턴 [{role, content}] 리스트. 멀티턴 메모리용(하위 호환).
             텍스트 user/assistant 메시지만 포함한다(tool_result 블록 제외).
             현재 발화(user_text)는 여기에 포함하지 않는다(함수 내부에서 추가됨).
    """
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

    # 멀티턴 메모리: 이전 대화 턴이 있으면 앞에 붙이고 현재 발화를 마지막에 추가한다.
    prior = list(history) if history else []
    cur_msg = {"role": "user", "content": user_text}

    if PROVIDER == "claude":
        # Claude는 네이티브 토큰 스트리밍을 쓴다.
        msgs = prior + [cur_msg]
        yield from _stream_claude(msgs, system, traced_run_tool)
        return
    cfg = _OPENAI_COMPAT.get(PROVIDER)
    if cfg is None:
        raise RuntimeError(
            f"알 수 없는 LLM_PROVIDER={PROVIDER}. 가능: claude, ollama, gemini, groq."
        )
    msgs = prior + [cur_msg]
    yield from _stream_openai_compat(cfg, msgs, system, traced_run_tool)
