"""FastAPI 요청/응답 pydantic 모델."""

from __future__ import annotations

from pydantic import BaseModel


class HistoryTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    persona: str
    lang: str = "auto"            # auto | ko | en | vi | ne
    intent: str                  # 사용자 발화 또는 선택지 라벨
    is_action: bool = False      # True면 선택지 버튼 클릭(언어를 lang으로 명시)
    history: list[HistoryTurn] = []
    completed_tools: list[str] = []


class IntroResponse(BaseModel):
    body: str
    labels: list[str]
    header: str


class PersonaCard(BaseModel):
    id: str
    code: str
    name: str
    en: str
    nationality: str
    visa: str
    entry: str
    exit: str
    note: str
    visaExpiry: str = ""
    visaRenewal: str = ""
    visaMonthsLeft: int = 0
    visaStatus: str = ""
    visaRenewalNeeded: bool = False
