"""LifeRoad FastAPI 백엔드.

프론트(HTML/JS, Cloudflare Pages)가 호출하는 API. Claude+MCP tool 로직은
기존 코어를 그대로 재사용한다. 페르소나는 minh suman 2명만 노출한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import threading

from dotenv import load_dotenv

# 키 로딩은 반드시 llm_provider import 전에 끝낸다(코어가 import 시 키를 동결).
# 순서: repo 안 .env 먼저(팀원 방식 유지) → 없으면 외부 ~/.liferoad/.env 보충.
# load_dotenv는 이미 설정된 변수를 덮지 않으므로 repo .env가 우선한다.
load_dotenv()
load_dotenv(os.path.expanduser("~/.liferoad/.env"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from shared.personas import PERSONAS
from shared.system_prompt import LANGUAGES, detect_lang, build_system_prompt
from shared.llm_provider import run_chat_stream, strip_emoji
from backend import core
from backend.fraud_api import router as fraud_router
from backend.schemas import ChatRequest, IntroResponse, PersonaCard

logger = logging.getLogger("liferoad")

app = FastAPI(title="LifeRoad AI Agent API")
app.include_router(fraud_router)  # 사기탐지 관제 API(/fraud/*) - 콘솔(8002)과 폰이 사용

# CORS: 프론트(Cloudflare Pages)와 백엔드가 다른 오리진이라 필수.
# 로컬은 http.server(8000), 배포는 *.pages.dev. 환경변수로 추가 오리진을 받는다.
_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8002",   # 사기탐지 관제 콘솔(fraud_console)
    "http://127.0.0.1:8002",
    "http://localhost:8010",   # 로컬 프리뷰 검증용
    "http://127.0.0.1:8010",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
_extra = os.environ.get("CORS_ORIGINS", "")
if _extra:
    _origins += [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.pages\.dev",  # Cloudflare Pages 프리뷰 도메인 허용
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_lang(lang: str) -> str:
    """lang=auto는 ko로 고정(첫 화면 규칙). 미지원 코드도 ko로 폴백."""
    if lang == "auto" or lang not in LANGUAGES:
        return "ko"
    return lang


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/personas", response_model=list[PersonaCard])
def personas():
    """시연 대상 2명(minh, suman)의 카드 데이터를 반환한다."""
    return [core.persona_card(PERSONAS[pid]) for pid in ("minh", "suman")]


# ---------------------------------------------------------------------------
# 서류 PDF 다운로드
# ---------------------------------------------------------------------------
# form_autofill이 생성한 PDF만 서빙한다. 파일명 허용 문자를 제한하고
# 실제 경로가 output 폴더 안인지 다시 확인해 경로 탈출을 이중 차단한다.

_DOWNLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.pdf$")


@app.get("/download/{filename}")
def download(filename: str):
    """채팅 카드의 다운로드 단추가 호출한다. 생성된 신청서 PDF를 내려준다."""
    from mcp_servers.docs.tools import OUTPUT_DIR

    if not _DOWNLOAD_NAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="잘못된 파일명입니다.")
    path = os.path.realpath(os.path.join(OUTPUT_DIR, filename))
    if not path.startswith(os.path.realpath(OUTPUT_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="잘못된 경로입니다.")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="파일이 없습니다. 신청서를 먼저 작성해 주세요.")
    # filename 인자로 받는 사람용 한글 파일명을 지정한다(Content-Disposition).
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=core.download_filename(filename),
    )


@app.get("/intro", response_model=IntroResponse)
def intro(
    persona: str = Query("minh"),
    lang: str = Query("auto"),
):
    """첫 화면 AI 추천 인트로. 상황 요약 본문 + 선제 선택지 라벨."""
    reply_lang = _resolve_lang(lang)
    if persona not in PERSONAS:
        # 조용히 다른 사람으로 바꿔치기하지 않는다. 클라이언트 버그를 드러낸다.
        raise HTTPException(status_code=400, detail=f"unknown persona: {persona}")
    body, labels = core.ai_recommend_actions(persona, reply_lang)
    return IntroResponse(
        body=body,
        labels=labels,
        header=core.START_HEADER.get(reply_lang, core.START_HEADER["ko"]),
    )


# ---------------------------------------------------------------------------
# /chat SSE 스트리밍
# ---------------------------------------------------------------------------
# run_chat_stream은 동기 제너레이터다. 그 안에서 on_step이 동기로 호출된다.
# 백그라운드 스레드에서 제너레이터를 돌리고 queue.Queue로 이벤트를 모아
# async로 흘리면 토큰과 step이 발생 순서대로 SSE에 실린다.

_SENTINEL = object()


def _sse(event: str, data: dict) -> dict:
    """sse_starlette EventSourceResponse가 먹는 dict 형식으로 변환한다."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


@app.post("/chat")
async def chat(req: ChatRequest):
    """대화 1턴을 SSE로 스트리밍한다.

    이벤트: step(tool 단계), token(텍스트 델타), final(마커 제거 본문+선택지),
    error(한국어 안내), end(종료).
    """
    if req.persona not in PERSONAS:
        raise HTTPException(status_code=400, detail=f"unknown persona: {req.persona}")
    persona = req.persona

    # 응답 언어 확정. 직접입력(is_action=False)이고 auto면 질문 언어를 감지한다.
    # 버튼 클릭(is_action=True)이면 프론트가 직전 답변 언어를 lang으로 명시한다.
    if req.lang == "auto" and not req.is_action:
        reply_lang = detect_lang(req.intent)
    else:
        reply_lang = _resolve_lang(req.lang)

    lang_directive = LANGUAGES[reply_lang]["instruct"]
    user_text = f"[페르소나: {persona}] [답변 언어 강제: {lang_directive}] {req.intent}"
    system = build_system_prompt(reply_lang, persona)

    # 턴별 모델 라우팅: 서류 관련 발화는 Sonnet(정확), 그 외는 Haiku(속도).
    model = core.pick_model(req.intent)

    # 멀티턴 히스토리. 프론트가 보낸 메시지에서 직전 3턴을 잘라 쓴다.
    msgs = [{"role": t.role, "content": t.content} for t in req.history]
    history = core.build_history(msgs, max_turns=3)

    completed = set(req.completed_tools)

    q: queue.Queue = queue.Queue()

    def worker():
        """백그라운드 스레드에서 run_chat_stream을 돌려 이벤트를 큐에 넣는다."""
        step_idx = {"n": 0}

        def on_step(kind, payload):
            step_idx["n"] += 1
            name = payload.get("name", "")
            if kind == "tool_error":
                q.put(_sse("step", {
                    "i": step_idx["n"], "name": name,
                    "label": core.TOOL_LABELS.get(name, name),
                    "is_error": True, "summary": f"{name} 오류",
                    "card": None,
                }))
            else:
                out = payload.get("output", {}) or {}
                completed.add(name)
                # form_autofill이 PDF를 생성했으면 카드에 다운로드 링크를 붙인다.
                card = core.attach_download(out.get("card"), out.get("numbers"))
                q.put(_sse("step", {
                    "i": step_idx["n"], "name": name,
                    "label": core.TOOL_LABELS.get(name, name),
                    "is_error": False,
                    "summary": out.get("summary", ""),
                    "card": card,
                }))

        acc = []
        try:
            for chunk in run_chat_stream(
                user_text, system, core.run_tool,
                on_step=on_step, history=history, model=model,
            ):
                if chunk:
                    acc.append(chunk)
                    q.put(_sse("token", {"t": chunk}))
            full = strip_emoji("".join(acc))
            text_no_done, is_done = core.parse_done_marker(full)
            body, next_labels = core.split_answer_and_actions(text_no_done)
            # 작업이 안 끝났는데 라벨이 비면 폴백으로 1~2개 채운다.
            if not next_labels and not is_done:
                fallback = core.start_action_labels(persona, reply_lang, exclude_tools=completed)
                next_labels = fallback[:2]
            q.put(_sse("final", {
                "body": body,
                "next_labels": next_labels,
                "is_done": is_done,
                "header": core.NEXT_HEADER.get(reply_lang, core.NEXT_HEADER["ko"]),
                "done_caption": core.DONE_CAPTION.get(reply_lang, core.DONE_CAPTION["ko"]) if is_done else None,
                "completed_tools": sorted(completed),
                "lang": reply_lang,
            }))
        except Exception as e:
            logger.exception("chat 스트리밍 실패: %r", e)
            q.put(_sse("error", {"message": core.korean_error_msg(e)}))
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    async def event_gen():
        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is _SENTINEL:
                yield _sse("end", {})
                break
            yield item

    return EventSourceResponse(event_gen())
