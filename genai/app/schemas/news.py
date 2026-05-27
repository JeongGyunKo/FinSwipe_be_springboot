from pydantic import BaseModel, Field
from typing import Any


# ── 요청 모델 ──────────────────────────────────────────────────────────────────

class EnrichTextRequest(BaseModel):
    """Spring Boot AnalyzerService와 호환되는 enrich-text 요청"""
    news_id: str
    title: str = ""
    link: str = ""
    article_text: str
    summary_text: str | None = None
    ticker: list[str] | str | None = None  # list 또는 단일 문자열 모두 허용

    @property
    def tickers(self) -> list[str] | None:
        if self.ticker is None:
            return None
        if isinstance(self.ticker, str):
            return [self.ticker] if self.ticker else None
        return self.ticker or None


class NewsAnalyzeRequest(BaseModel):
    """새 뉴스 분석 API 요청"""
    source_url: str
    title: str
    content: str
    summary: str | None = None
    tickers: list[str] | None = None


class TickerSummaryRequest(BaseModel):
    user_level: int = Field(default=3, ge=1, le=5)


# ── 응답 모델 ──────────────────────────────────────────────────────────────────

class SentimentResponse(BaseModel):
    label: str
    score: float | None = None


class LocalizedResponse(BaseModel):
    title: str | None = None
    summary_3lines: list[str] | None = None
    xai: Any | None = None


class EnrichTextResponse(BaseModel):
    """Spring Boot 호환 응답 — AnalyzerService.parseResponse() 참고"""
    outcome: str
    sentiment: SentimentResponse | None = None
    summary_3lines: list[str] | None = None
    xai: Any | None = None
    localized: LocalizedResponse | None = None


class TickerSummaryResponse(BaseModel):
    ticker: str
    level: int
    summary: str
    key_points: list[str] = []
    sentiment_overview: str
    article_count: int
