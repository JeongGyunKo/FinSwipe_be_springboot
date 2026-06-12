from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_LEVEL_DEPTH = {
    1: "초등학생도 이해할 수 있을 정도로 쉽게, 비유를 들어 설명해주세요. 전문 용어는 쓰지 마세요.",
    2: "주식 초보 투자자에게 설명하듯 쉽게 설명하되 기본 용어는 사용해도 됩니다.",
    3: "PER, RSI, MACD 같은 중급 개념을 알고 있는 투자자 수준으로 설명해주세요.",
    4: "재무 분석과 기술적 분석을 이해하는 투자자에게 심화 내용을 포함해 설명해주세요.",
    5: "전문 투자자 수준으로 정량적 분석, 리스크 팩터, 알파 시그널 관점까지 포함해 설명해주세요.",
}

_TENDENCY_FOCUS = {
    "가치투자형 투자자": "기업 내재가치와 장기 펀더멘털 관점에서 분석하세요. PER·PBR·FCF 같은 재무지표를 중심으로 설명하세요.",
    "모멘텀형 투자자": "단기 가격 흐름과 시장 추세 관점에서 분석하세요. RSI·MACD 기술적 시그널과 모멘텀을 중심으로 설명하세요.",
    "안정추구형 투자자": "리스크 요소와 하방 리스크를 중심으로 분석하세요. 포트폴리오 안정성과 손실 방어 관점에서 설명하세요.",
    "거시경제형 투자자": "금리·환율·경기 사이클 등 거시경제 관점에서 분석하세요. 매크로 환경과의 연결성을 중심으로 설명하세요.",
    "탐색형 투자자": "최대한 쉽고 친절하게 설명해주세요. 전문 용어는 괄호 안에 간단히 풀어 설명하세요.",
}

_CHAT_MODEL = "gemini-2.5-flash-lite"


class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryItem] = []
    user_level: int = 3
    user_tendency: str = "탐색형 투자자"
    user_tickers: list[str] = []


def _build_system_prompt(level: int, tendency: str, tickers: list[str]) -> str:
    level_clamped = max(1, min(5, level))
    depth = _LEVEL_DEPTH.get(level_clamped, _LEVEL_DEPTH[3])
    focus = _TENDENCY_FOCUS.get(tendency, _TENDENCY_FOCUS["탐색형 투자자"])
    ticker_str = ", ".join(tickers) if tickers else "없음"

    return f"""당신은 개인화 금융 투자 AI 어시스턴트입니다.
유저의 관심 종목과 투자 성향에 맞춰 투자 관련 질문에 답변합니다.

[유저 프로필]
- 투자 레벨: {level_clamped}레벨 (1~5 중)
- 투자 성향: {tendency}
- 관심 종목: {ticker_str}

[설명 깊이]
{depth}

[분석 관점]
{focus}

[답변 규칙]
- 반드시 한국어로 답변
- 관심 종목과 관련된 질문은 해당 종목 맥락에서 구체적으로 답변
- 투자 권유가 아닌 정보 제공 관점으로 설명
- 간결하고 명확하게 — 불필요한 서두 없이 핵심부터
- 마크다운 헤더(##)는 쓰지 말고, 필요시 줄바꿈과 •로 구분"""


def _build_user_prompt(message: str, history: list[HistoryItem]) -> str:
    if not history:
        return message

    lines = ["[대화 기록]"]
    for item in history:
        role_label = "유저" if item.role == "user" else "AI"
        lines.append(f"{role_label}: {item.content}")
    lines.append("")
    lines.append(f"[유저 질문]\n{message}")
    return "\n".join(lines)


@router.post("/message")
async def chat_message(req: ChatRequest) -> dict:
    """유저 챗봇 메시지 처리 — Gemini로 응답 생성."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="메시지가 비어 있습니다.")

    system_prompt = _build_system_prompt(req.user_level, req.user_tendency, req.user_tickers)
    user_prompt = _build_user_prompt(req.message, req.history)

    try:
        reply = await asyncio.to_thread(
            gemini_generate_content,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=_CHAT_MODEL,
            temperature=0.7,
            request_label="chat",
        )
    except Exception as exc:
        logger.error("[챗봇] Gemini 호출 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="AI 응답 생성 중 오류가 발생했습니다.") from exc

    return {"reply": reply}
