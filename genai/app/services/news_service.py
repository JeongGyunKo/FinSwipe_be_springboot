"""뉴스 분석 서비스
파이프라인: FinBERT(감성) + Gemini(요약+번역) 병렬 실행
           LIME(XAI)는 백그라운드 처리 → 응답 블로킹 없음
"""
import asyncio
import logging
from datetime import date

from app.prompts.news_prompts import (
    SUMMARIZE_SYSTEM,
    TICKER_SUMMARY_SYSTEM,
    build_summarize_messages,
    build_ticker_summary_messages,
)
from app.services.gemini_client import call_gemini, extract_json
from app.database import get_pool

logger = logging.getLogger(__name__)


async def enrich_article(
    news_id: str,
    title: str,
    article_text: str,
    summary_text: str | None = None,
    tickers: list[str] | None = None,
) -> dict:
    """기사 전체 분석 파이프라인

    FinBERT + Gemini 병렬 실행 → 즉시 응답
    LIME XAI → 백그라운드에서 DB 직접 업데이트 (응답 블로킹 없음)

    Returns:
        Spring Boot AnalyzerService 호환 응답 dict
    """
    if not article_text or not article_text.strip():
        logger.warning("[분석] 본문 없음 → 스킵: %s", news_id[:60])
        return _unavailable_response()

    # ── FinBERT + Gemini 병렬 실행 ────────────────────────────────────────
    sentiment_task = asyncio.create_task(_run_finbert(title, article_text))
    gemini_task    = asyncio.create_task(
        _run_gemini_summarize(title, article_text, summary_text, tickers)
    )
    sentiment_result, summary_data = await asyncio.gather(
        sentiment_task, gemini_task, return_exceptions=False
    )

    # ── LIME XAI 백그라운드 실행 (응답 반환 후 DB 업데이트) ─────────────
    asyncio.create_task(
        _run_lime_background(news_id, article_text, sentiment_result.label)
    )

    return {
        "outcome": "analyzed",
        "sentiment": {
            "label": sentiment_result.label,
            "score": sentiment_result.score,
        },
        "summary_3lines": summary_data.get("summary_3lines"),
        "xai": None,  # LIME 완료 후 DB에 직접 업데이트됨
        "localized": {
            "title": summary_data.get("localized", {}).get("title"),
            "summary_3lines": summary_data.get("localized", {}).get("summary_3lines"),
            "xai": None,
        },
    }


# ── 내부 실행 함수 ────────────────────────────────────────────────────────────

async def _run_finbert(title: str, article_text: str):
    """FinBERT를 별도 스레드에서 실행 (CPU bound)"""
    loop = asyncio.get_running_loop()
    try:
        from app.services.sentiment.finbert import analyze_sentiment
        return await loop.run_in_executor(None, analyze_sentiment, title, article_text)
    except Exception as e:
        logger.error("[FinBERT] 오류: %s", e)
        from app.services.sentiment.chunking import ArticleSentimentResult
        return ArticleSentimentResult("neutral", 0.5, 0.33, 0.33, 0.34, 0.0, 0)


async def _run_gemini_summarize(title: str, article_text: str,
                                summary_text: str | None,
                                tickers: list[str] | None) -> dict:
    """Gemini 요약 + 한국어 번역"""
    messages = build_summarize_messages(title, article_text, summary_text, tickers)
    try:
        raw = await call_gemini(
            system=SUMMARIZE_SYSTEM,
            messages=messages,
            use_thinking=False,
            max_tokens=1024,
        )
        return extract_json(raw)
    except Exception as e:
        logger.error("[Gemini] 요약 실패: %s", e)
        return {}


async def _run_lime_background(source_url: str, article_text: str,
                               sentiment_label: str) -> None:
    """LIME XAI 백그라운드 실행 → DB xai/xai_ko 컬럼 직접 업데이트"""
    loop = asyncio.get_running_loop()
    try:
        from app.services.sentiment.finbert import get_predict_fn
        from app.services.xai.lime_explainer import explain_sentiment, xai_result_to_dict
        import json

        predict_fn = get_predict_fn()
        result = await loop.run_in_executor(
            None, explain_sentiment, article_text, sentiment_label, predict_fn
        )
        xai_dict = xai_result_to_dict(result)

        if not xai_dict.get("keywords") and not xai_dict.get("highlights"):
            return

        xai_json = json.dumps(xai_dict, ensure_ascii=False)

        pool = get_pool()
        # source_url에 cacheBuster 쿼리스트링이 붙어있을 수 있으므로 앞부분만 매칭
        clean_url = source_url.split("?")[0]
        updated = await pool.execute(
            """
            UPDATE news_articles
            SET xai    = $1::jsonb,
                xai_ko = $1::jsonb,
                updated_at = NOW()
            WHERE source_url = $2
              AND xai IS NULL
            """,
            xai_json, clean_url,
        )
        logger.debug("[LIME] XAI 업데이트 완료: %s (%s)", clean_url[:60], updated)

    except Exception as e:
        logger.warning("[LIME] 백그라운드 실패 (무시): %s | %s", source_url[:60], e)


# ── 티커별 뉴스 요약 ──────────────────────────────────────────────────────────

async def get_ticker_summary(ticker: str, user_level: int) -> dict:
    """티커별 오늘 뉴스 요약 (레벨 맞춤)"""
    pool = get_pool()
    today = date.today()

    rows = await pool.fetch(
        """
        SELECT headline, summary_3lines, summary_3lines_ko, sentiment_label
        FROM news_articles
        WHERE $1 = ANY(tickers)
          AND published_at::date = $2
          AND sentiment_label IS NOT NULL
          AND sentiment_label NOT IN ('unavailable', 'unknown', '_clean_filtered')
        ORDER BY published_at DESC
        LIMIT 10
        """,
        ticker, today,
    )

    if not rows:
        return {
            "ticker": ticker,
            "level": user_level,
            "summary": f"오늘 {ticker} 관련 뉴스가 없습니다.",
            "key_points": [],
            "sentiment_overview": "neutral",
            "article_count": 0,
        }

    articles = [dict(r) for r in rows]
    messages = build_ticker_summary_messages(ticker, user_level, articles)

    try:
        raw = await call_gemini(
            system=TICKER_SUMMARY_SYSTEM,
            messages=messages,
            use_thinking=False,
            max_tokens=1024,
        )
        result = extract_json(raw)
        result["ticker"] = ticker
        result["level"] = user_level
        result["article_count"] = len(articles)
        return result
    except Exception as e:
        logger.error("[Gemini] 티커 요약 실패: %s | %s", ticker, e)
        sentiments = [a.get("sentiment_label", "neutral") for a in articles]
        pos, neg = sentiments.count("positive"), sentiments.count("negative")
        return {
            "ticker": ticker,
            "level": user_level,
            "summary": f"{ticker} 관련 뉴스 {len(articles)}건이 있습니다.",
            "key_points": [],
            "sentiment_overview": "positive" if pos > neg else "negative" if neg > pos else "mixed",
            "article_count": len(articles),
        }


def _unavailable_response() -> dict:
    return {
        "outcome": "fatal_failure",
        "sentiment": {"label": "unavailable", "score": None},
        "summary_3lines": None,
        "xai": None,
        "localized": {"title": None, "summary_3lines": None, "xai": None},
    }
