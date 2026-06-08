from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core import get_settings
from app.db.postgres import connect_postgres
from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)

_LEVEL_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

_LEVEL_DEPTH = {
    1: "초등학생도 이해할 수 있을 정도로 매우 쉽게, 비유를 들어 설명해주세요. 전문 용어는 쓰지 마세요.",
    2: "주식을 시작한 지 얼마 안 된 초보 투자자에게 설명하듯 쉽게 설명하되 기본 용어는 사용해도 됩니다.",
    3: "PER, RSI, MACD 같은 중급 개념을 알고 있는 투자자 수준으로 설명해주세요.",
    4: "재무 분석과 기술적 분석을 이해하는 투자자에게 설명하듯 심화 내용을 포함해주세요.",
    5: "전문 투자자 수준으로 정량적 분석, 리스크 팩터, 알파 시그널 관점까지 포함해 설명해주세요.",
}

_TENDENCY_FOCUS = {
    "가치투자형 투자자": "기업 내재가치와 장기 펀더멘털 관점에서 분석하세요. PER·PBR·FCF 같은 재무지표를 중심으로 오늘 뉴스가 밸류에이션에 미치는 영향을 설명하세요.",
    "모멘텀형 투자자": "단기 가격 흐름과 시장 추세 관점에서 분석하세요. 오늘 뉴스가 RSI·MACD 기술적 시그널과 모멘텀에 어떤 영향을 주는지 중심으로 설명하세요.",
    "안정추구형 투자자": "리스크 요소와 하방 리스크를 중심으로 분석하세요. 오늘 뉴스가 포트폴리오 안정성에 미치는 영향을 손실 방어 관점에서 설명하세요.",
    "거시경제형 투자자": "금리·환율·경기 사이클 등 거시경제 관점에서 분석하세요. 오늘 뉴스가 매크로 환경과 어떻게 연결되는지 설명하세요.",
    "탐색형 투자자": "최대한 쉽고 친절하게 설명해주세요. 전문 용어는 괄호 안에 간단히 풀어서 설명하세요.",
}

_DEFAULT_TENDENCY_FOCUS = _TENDENCY_FOCUS["탐색형 투자자"]

_SYSTEM_PROMPT = """당신은 개인화 금융 뉴스 분석 전문가입니다.
특정 종목에 대해 오늘 하루(어제 장 마감 이후~현재) 나온 뉴스를 종합 분석하여
해당 투자자의 성향과 지식 레벨에 맞는 일일 요약을 제공합니다.

규칙:
- 반드시 한국어로 답변하세요
- 3~5문장으로 핵심만 짚어주세요
- 오늘의 주요 이벤트가 무엇인지, 이 투자자 입장에서 어떻게 봐야 하는지 중심으로 작성하세요
- 단순 뉴스 나열이 아니라 종합적 시각으로 작성하세요
- 긍정/부정 뉴스가 섞인 경우 전체 흐름을 균형 있게 정리하세요"""


def _fetch_user_profile(user_id: str, settings) -> dict | None:
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tickers, level, tendency FROM user_profiles WHERE id = CAST(%s AS UUID)",
                (user_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "tickers": list(row["tickers"] or []),
        "level": int(row["level"] or 3),
        "tendency": str(row["tendency"] or "탐색형 투자자"),
    }


def _fetch_ticker_articles(ticker: str, settings) -> list[dict]:
    """어제 미국 장 마감(16:00 ET ≈ NOW()-24h) 이후 기사를 감성점수 절대값 내림차순으로 최대 10건."""
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT headline_ko, headline, sentiment_label, sentiment_score,
                       sentiment_reason, published_at
                FROM news_articles
                WHERE %s = ANY(tickers)
                  AND published_at >= NOW() - INTERVAL '24 hours'
                  AND (headline_ko IS NOT NULL OR headline IS NOT NULL)
                ORDER BY ABS(sentiment_score) DESC, published_at DESC
                LIMIT 10
                """,
                (ticker,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def _sentiment_overview(articles: list[dict]) -> dict:
    pos = sum(1 for a in articles if (a.get("sentiment_label") or "") == "positive")
    neg = sum(1 for a in articles if (a.get("sentiment_label") or "") == "negative")
    scores = [float(a["sentiment_score"]) for a in articles if a.get("sentiment_score") is not None]
    return {
        "positive": pos,
        "negative": neg,
        "neutral": len(articles) - pos - neg,
        "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
    }


def _build_digest_prompt(ticker: str, articles: list[dict], level: int, tendency: str) -> str:
    lines = []
    for i, a in enumerate(articles[:8], 1):
        title = (a.get("headline_ko") or a.get("headline") or "").strip()
        label = a.get("sentiment_label") or "neutral"
        score = float(a.get("sentiment_score") or 0.0)
        reason = (a.get("sentiment_reason") or "").strip()
        lines.append(f"{i}. [{label}|{score:+.2f}] {title}")
        if reason:
            lines.append(f"   → {reason[:120]}")

    depth = _LEVEL_DEPTH.get(level, _LEVEL_DEPTH[3])
    focus = _TENDENCY_FOCUS.get(tendency, _DEFAULT_TENDENCY_FOCUS)
    label_str = _LEVEL_LABELS.get(level, "중급")

    return (
        f"[종목] {ticker}\n"
        f"[사용자 프로필] 지식 레벨: {level}/5 ({label_str}) / 투자 성향: {tendency}\n\n"
        f"[오늘 뉴스 {len(articles)}건]\n"
        + "\n".join(lines)
        + f"\n\n[분석 깊이] {depth}\n"
        f"[성향 초점] {focus}\n\n"
        f"위 내용을 종합하여 오늘 {ticker}에 대한 맞춤 일일 요약을 작성하세요."
    )


def _fetch_technicals(ticker: str) -> dict | None:
    try:
        import numpy as np
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="3mo", interval="1d")
        if hist.empty or len(hist) < 26:
            return None

        prices = hist["Close"].values.astype(float)
        volumes = hist["Volume"].values.astype(float)

        current_price = round(float(prices[-1]), 2)
        change_1d = round((prices[-1] / prices[-2] - 1) * 100, 2) if len(prices) >= 2 else None
        change_1m = round((prices[-1] / prices[-22] - 1) * 100, 2) if len(prices) >= 22 else None
        volume_ratio = round(float(volumes[-1] / volumes[-5:].mean()), 2) if len(volumes) >= 5 else None

        # RSI (14일)
        deltas = np.diff(prices[-29:])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = gains[-14:].mean()
        avg_loss = losses[-14:].mean()
        rsi = round(100 - 100 / (1 + avg_gain / avg_loss), 1) if avg_loss != 0 else 100.0

        # MACD (12/26/9)
        def ema(arr: "np.ndarray", span: int) -> "np.ndarray":
            k = 2 / (span + 1)
            r = np.zeros(len(arr))
            r[0] = arr[0]
            for i in range(1, len(arr)):
                r[i] = arr[i] * k + r[i - 1] * (1 - k)
            return r

        ema12 = ema(prices, 12)
        ema26 = ema(prices, 26)
        macd_line = ema12 - ema26
        signal_line = ema(macd_line, 9)
        histogram = round(float(macd_line[-1] - signal_line[-1]), 4)

        return {
            "current_price": current_price,
            "change_pct_1d": change_1d,
            "change_pct_1m": change_1m,
            "volume_ratio": volume_ratio,
            "RSI": rsi,
            "RSI_signal": "과매수" if rsi > 70 else "과매도" if rsi < 30 else "중립",
            "MACD": {
                "macd": round(float(macd_line[-1]), 4),
                "signal": round(float(signal_line[-1]), 4),
                "histogram": histogram,
                "trend": "상승" if histogram > 0 else "하락",
            },
        }
    except Exception as exc:
        logger.warning("[다이제스트] %s 기술적 지표 수집 실패: %s", ticker, exc)
        return None


def generate_digest(user_id: str) -> dict:
    settings = get_settings()

    profile = _fetch_user_profile(user_id, settings)
    if profile is None:
        return {"error": "사용자를 찾을 수 없습니다.", "digests": []}

    tickers: list[str] = profile["tickers"]
    level: int = profile["level"]
    tendency: str = profile["tendency"]

    if not tickers:
        return {
            "digests": [],
            "user_level": level,
            "user_tendency": tendency,
            "message": "관심 티커가 없습니다. 티커를 먼저 추가하세요.",
        }

    digests = []
    for ticker in tickers[:10]:
        articles = _fetch_ticker_articles(ticker, settings)

        if not articles:
            digests.append({
                "ticker": ticker,
                "articles_count": 0,
                "message": "오늘 관련 뉴스가 없습니다.",
                "sentiment_overview": None,
                "summary": None,
                "technical_indicators": _fetch_technicals(ticker),
            })
            continue

        overview = _sentiment_overview(articles)

        try:
            prompt = _build_digest_prompt(ticker, articles, level, tendency)
            summary = gemini_generate_content(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                model=settings.gemini_summary_model,
                temperature=0.3,
                request_label="daily_digest",
            ).strip()
        except Exception as exc:
            logger.error("[다이제스트] %s 요약 생성 실패: %s", ticker, exc)
            summary = None

        technicals = _fetch_technicals(ticker)

        digests.append({
            "ticker": ticker,
            "articles_count": len(articles),
            "sentiment_overview": overview,
            "summary": summary,
            "technical_indicators": technicals,
        })

    return {
        "digests": digests,
        "user_level": level,
        "user_tendency": tendency,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
