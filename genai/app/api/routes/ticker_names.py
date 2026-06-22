from __future__ import annotations
import json
import logging
import re
from fastapi import APIRouter
from pydantic import BaseModel
from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ticker-names", tags=["ticker-names"])


class TickerTranslateRequest(BaseModel):
    ticker: str
    corp: str


class TickerTranslateResponse(BaseModel):
    ko: str
    aliases: list[str]


@router.post("/translate")
def translate_ticker(body: TickerTranslateRequest) -> TickerTranslateResponse:
    prompt = (
        f"회사명: {body.corp}\n"
        f"티커: {body.ticker}\n\n"
        "한국 주식 투자자 커뮤니티(네이버 증권, 종토방)에서 실제로 쓰는 표현으로 변환하세요.\n"
        'JSON만 출력: {"ko": "대표 한글명", "aliases": ["변형1", "변형2"]}\n'
        "규칙: 브랜드 영문 일부는 유지 가능 (스페이스X, xAI). aliases는 최대 4개."
    )
    try:
        raw = gemini_generate_content(
            model="gemini-2.5-flash-lite",
            system_prompt="You are a Korean stock community name converter. Output JSON only, no explanation.",
            user_prompt=prompt,
            temperature=0.0,
            request_label="ticker_translate",
        )
        m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            ko = str(data.get("ko", body.corp)).strip()
            aliases = [str(a).strip() for a in data.get("aliases", []) if str(a).strip()]
            return TickerTranslateResponse(ko=ko or body.corp, aliases=aliases)
    except Exception:
        logger.exception("[티커번역] Gemini 실패: %s / %s", body.ticker, body.corp)
    return TickerTranslateResponse(ko=body.corp, aliases=[body.ticker.lower()])
