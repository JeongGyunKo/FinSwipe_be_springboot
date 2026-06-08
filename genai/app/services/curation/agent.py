from __future__ import annotations

import logging
from app.core import get_settings
from app.db.postgres import connect_postgres
from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 개인화 금융 뉴스 큐레이터입니다.
사용자의 관심 티커, 투자 성향, 지식 레벨을 고려하여
오늘 가장 중요한 뉴스 3개를 선별하고, 각각 왜 중요한지 한 문장으로 설명하세요.
반드시 한국어로 답변하고, JSON 배열로만 응답하세요.
"""


def curate_news(user_id: str) -> dict:
    settings = get_settings()

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            # 사용자 프로필
            cur.execute(
                "SELECT tickers, level, tendency FROM user_profiles WHERE id = %s",
                (user_id,),
            )
            profile = cur.fetchone()
            if not profile or not profile["tickers"]:
                return {"articles": [], "message": "관심 티커가 없습니다."}

            tickers = profile["tickers"]
            level = profile.get("level") or 1
            tendency = profile.get("tendency") or "탐색형"

            # 최근 24시간 관심 티커 기사 (분석 완료된 것)
            cur.execute(
                """
                SELECT id, headline_ko, sentiment_label, sentiment_score, sentiment_reason,
                       tickers, published_at
                FROM news_articles
                WHERE tickers && %s::text[]
                  AND sentiment_reason IS NOT NULL
                  AND headline_ko IS NOT NULL
                  AND published_at >= NOW() - INTERVAL '24 hours'
                ORDER BY ABS(sentiment_score) DESC, published_at DESC
                LIMIT 20
                """,
                (tickers,),
            )
            articles = cur.fetchall()

    if not articles:
        return {"articles": [], "message": "최근 24시간 내 관련 뉴스가 없습니다."}

    articles_text = "\n".join([
        f"{i+1}. [{a['sentiment_label']}|{a['sentiment_score']:.2f}] {a['headline_ko']} "
        f"(티커: {', '.join(a['tickers'][:3])})"
        for i, a in enumerate(articles)
    ])

    user_prompt = f"""
관심 티커: {', '.join(tickers)}
투자 성향: {tendency} / 지식 레벨: {level}/5

오늘의 뉴스 목록 (감성점수 절대값 높은 순):
{articles_text}

위 뉴스에서 이 투자자에게 가장 중요한 3개를 선택하고 JSON으로 응답하세요:
[
  {{"rank": 1, "headline": "제목", "reason": "왜 중요한지 한 문장", "sentiment": "positive/negative/neutral", "article_number": 번호}},
  ...
]
"""

    try:
        raw = gemini_generate_content(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.gemini_summary_model,
            temperature=0.2,
            request_label="news_curation",
        )

        import json, re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        curated = json.loads(match.group()) if match else []

        # article_number로 실제 기사 ID 매핑
        result = []
        for item in curated[:3]:
            num = item.get("article_number", 1) - 1
            if 0 <= num < len(articles):
                a = articles[num]
                result.append({
                    "rank": item["rank"],
                    "article_id": str(a["id"]),
                    "headline_ko": a["headline_ko"],
                    "reason": item.get("reason", ""),
                    "sentiment": item.get("sentiment", a["sentiment_label"]),
                    "sentiment_score": float(a["sentiment_score"] or 0),
                    "tickers": a["tickers"],
                })

        return {"articles": result, "tickers": tickers, "tendency": tendency}

    except Exception as e:
        logger.error("[큐레이션] 실패: %s", e, exc_info=True)
        return {"articles": [], "error": "큐레이션 처리 중 오류가 발생했습니다."}
