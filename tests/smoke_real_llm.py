"""실제 Claude API를 붙여 마커 형식과 흐름을 검증하는 스모크 스크립트.

pytest가 수집하지 않도록 파일명에 test_ 접두어를 붙이지 않았다.
실행: .venv/bin/python tests/smoke_real_llm.py
검증 항목 (00_현황판.md "실대화 검증" a~e):
  (a) 첫 화면 AI 추천이 상황에 맞게 나오는가
  (b) LLM이 <<NEXT>>/<<DONE>> 마커 형식을 지키는가
  (c) 종료 후 재추천에서 완료 작업이 빠지는가
  (d) 멀티턴 후속 질문("왜 그래?")이 맥락을 잡는가
  (e) 예외 시 한국어 안내가 나오는가 (LLM 무관, 로컬 함수)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 키 로딩: repo 안 .env 먼저(팀원 방식) → 없으면 외부 ~/.liferoad/.env 보충.
from dotenv import load_dotenv
load_dotenv()
load_dotenv(os.path.expanduser("~/.liferoad/.env"))

from backend.core import (
    TODAY,
    korean_error_msg,
    parse_done_marker,
    run_tool,
    split_answer_and_actions,
)
from shared.llm_provider import run_chat, strip_emoji
from shared.system_prompt import LANGUAGES, build_system_prompt

PERSONA = "minh"
LANG = "ko"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, note: str = ""):
    results.append((name, ok, note))
    print(f"\n{'PASS' if ok else 'FAIL'} [{name}] {note}")


def call(user_text: str, history=None):
    """run_chat 호출 후 (본문, 라벨들, is_done, tool호출목록)을 돌려준다."""
    tool_calls: list[str] = []

    def on_step(kind, payload):
        if kind == "tool_call":
            tool_calls.append(payload["name"])

    system = build_system_prompt(LANG, PERSONA)
    raw = run_chat(user_text, system, run_tool, on_step=on_step, history=history)
    raw = strip_emoji(raw)
    body, is_done = parse_done_marker(raw)
    body, labels = split_answer_and_actions(body)
    return body, labels, is_done, tool_calls


def tagged(text: str) -> str:
    directive = LANGUAGES[LANG]["instruct"]
    return f"[페르소나: {PERSONA}] [답변 언어 강제: {directive}] {text}"


# ---------------------------------------------------------------------------
# (a) 첫 화면 AI 추천 - ai_recommend_actions와 동일한 프롬프트
# ---------------------------------------------------------------------------
print("=" * 70)
print("(a) 첫 화면 AI 추천")
intro_prompt = tagged(
    f"오늘은 {TODAY}입니다. "
    "지금 이 사용자의 비자와 입국일과 출국 예정일과 오늘 날짜와 자산과 연금 납부 상황을 종합해 "
    "지금 가장 먼저 챙겨야 할 금융 행동을 우선순위로 3개 추천해 줘. "
    "짧은 인사와 핵심 상황 한 줄 요약 뒤에 <<NEXT>>로 추천 행동 3개를 적어 줘."
)
body, labels, _, _ = call(intro_prompt)
print("본문:", body)
print("추천 라벨:", labels)
record("a.첫화면_추천", bool(body.strip()) and 1 <= len(labels) <= 4,
       f"라벨 {len(labels)}개")

# ---------------------------------------------------------------------------
# (c) 재추천 - 연금 작업 완료 후 제외되는가
# ---------------------------------------------------------------------------
print("=" * 70)
print("(c) 완료 작업 제외 재추천")
re_prompt = intro_prompt + " 이미 처리한 작업은 제외해 줘: 연금 반환일시금 확인."
body, labels, _, _ = call(re_prompt)
print("본문:", body)
print("추천 라벨:", labels)
pension_leak = [l for l in labels if "연금" in l]
record("c.재추천_제외", bool(labels) and not pension_leak,
       f"라벨 {labels} / 연금 누출 {pension_leak or '없음'}")

# ---------------------------------------------------------------------------
# (b-1) 작업 요청 - tool 호출 + <<NEXT>> 라벨
# ---------------------------------------------------------------------------
print("=" * 70)
print("(b-1) 연금 계산 요청 - tool 호출과 <<NEXT>>")
q1 = tagged("출국 전에 국민연금 반환일시금을 얼마나 받을 수 있는지 계산해 주세요.")
body1, labels1, done1, tools1 = call(q1)
print("본문:", body1)
print("라벨:", labels1)
print("tool 호출:", tools1, "/ is_done:", done1)
record("b1.작업_NEXT", bool(tools1) and bool(labels1),
       f"tools={tools1}, 라벨 {len(labels1)}개")

history = [
    {"role": "user", "content": q1},
    {"role": "assistant", "content": body1},
]

# ---------------------------------------------------------------------------
# (d) 멀티턴 - "왜 그렇게 나와요?" 후속이 맥락을 잡는가
# ---------------------------------------------------------------------------
print("=" * 70)
print("(d) 멀티턴 후속 질문")
q2 = tagged("왜 그렇게 나오는 거예요?")
body2, labels2, _, _ = call(q2, history=history)
print("본문:", body2)
context_kept = any(k in body2 for k in ("연금", "반환일시금", "납부"))
record("d.멀티턴_맥락", bool(body2.strip()) and context_kept,
       "연금 맥락 유지" if context_kept else "맥락 단서 없음 - 본문 직접 확인")

# ---------------------------------------------------------------------------
# (b-2) 작업 매듭 - <<DONE>> 마커
# ---------------------------------------------------------------------------
print("=" * 70)
print("(b-2) 작업 종결 발화 - <<DONE>> 기대")
history2 = history + [
    {"role": "user", "content": q2},
    {"role": "assistant", "content": body2},
]
q3 = tagged("고마워요. 연금 문제는 이제 다 정리된 것 같아요. 더 할 건 없죠?")
body3, labels3, done3, _ = call(q3, history=history2)
print("본문:", body3)
print("라벨:", labels3, "/ is_done:", done3)
record("b2.종결_DONE", done3, "마커 감지됨" if done3 else "마커 미출력 - 소프트 종결 미준수")

# ---------------------------------------------------------------------------
# (e) 예외 한국어화 - 로컬 함수
# ---------------------------------------------------------------------------
print("=" * 70)
print("(e) 예외 한국어 안내")
samples = [
    ConnectionError("Connection refused"),
    TimeoutError("Request timed out"),
    RuntimeError("rate_limit_error: Number of requests exceeded"),
]
msgs = [korean_error_msg(e) for e in samples]
for e, m in zip(samples, msgs):
    print(f"  {type(e).__name__}: {m}")
all_korean = all(any("가" <= ch <= "힣" for ch in m) for m in msgs)
record("e.예외_한국어", all_korean, "전부 한국어" if all_korean else "영문 노출 있음")

# ---------------------------------------------------------------------------
print("=" * 70)
fails = [r for r in results if not r[1]]
print(f"\n총 {len(results)}건 중 PASS {len(results) - len(fails)} / FAIL {len(fails)}")
for name, ok, note in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {note}")
sys.exit(1 if fails else 0)
