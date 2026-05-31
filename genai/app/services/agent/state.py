from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict


class AnalysisState(TypedDict):
    # ── 입력 ──────────────────────────────────────────────────────────────────
    article_title: str
    article_text: str
    tickers: list[str]
    sentiment_label: str
    sentiment_score: float
    sentiment_reason: str
    user_level: int          # 1~5
    user_tendency: str       # 가치투자형 | 모멘텀형 | 안정추구형 | 공격성장형 | 인컴형 | 탐색형

    # ── 중간 결과 ─────────────────────────────────────────────────────────────
    price_data: Optional[dict]           # {ticker: [close prices]}
    technical_indicators: Optional[dict] # {ticker: {RSI, MACD, signal, trend}}

    # ── 최종 출력 ─────────────────────────────────────────────────────────────
    personalized_analysis: Optional[str]
    error: Optional[str]
