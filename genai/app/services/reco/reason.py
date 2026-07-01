"""개인화 피드 추천 이유 — (기사, 성향)별 한 줄 이유를 캐시하며 생성.

캐시 키가 (기사, 성향)이라 유저 수와 무관하게 토큰이 고정된다(같은 성향 유저는 공유).
BE가 피드의 상위 기사 id 묶음을 보내면, 캐시에 없는 것만 한 번의 Gemini 호출로 일괄 생성.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core import get_settings
from app.db.postgres import connect_postgres
from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)

_MAX_PER_CALL = 30

_SYSTEM_PROMPT = """당신은 금융 뉴스 추천 카피라이터입니다.
각 뉴스가 왜 이 투자자에게 지금 볼 가치가 있는지 한 줄로 설명합니다.

반드시 아래 JSON 형식으로만 답변하세요 (코드블록 없이, 순수 JSON만):
{"<기사id>": "<추천 이유>", ...}

규칙:
- 반드시 한국어
- 각 이유는 30자 이내, 담백하게
- 과장·투자 권유 금지
- 입력에 있는 기사 id를 키로 그대로 사용
- JSON 외 다른 텍스트 출력 금지"""


def _get_cached(article_ids: list[str], tendency: str, settings) -> dict[str, str]:
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT article_id, reason FROM reco_reason_cache WHERE tendency = %s AND article_id = ANY(%s)",
                (tendency, article_ids),
            )
            return {r["article_id"]: r["reason"] for r in cur.fetchall()}


def _fetch_articles(article_ids: list[str], settings) -> dict[str, dict]:
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text AS id, headline_ko, headline, sentiment_label, tickers
                FROM news_articles
                WHERE id::text = ANY(%s)
                """,
                (article_ids,),
            )
            return {r["id"]: dict(r) for r in cur.fetchall()}


def _save(reasons: dict[str, str], tendency: str, settings) -> None:
    if not reasons:
        return
    now = datetime.now(timezone.utc)
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO reco_reason_cache (article_id, tendency, reason, generated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (article_id, tendency)
                DO UPDATE SET reason = EXCLUDED.reason, generated_at = EXCLUDED.generated_at
                """,
                [(aid, tendency, reason, now) for aid, reason in reasons.items()],
            )
        conn.commit()


def _generate_missing(articles: dict[str, dict], tendency: str, settings) -> dict[str, str]:
    lines = []
    for aid, a in articles.items():
        title = (a.get("headline_ko") or a.get("headline") or "").strip()
        label = a.get("sentiment_label") or "neutral"
        tks = ",".join(a.get("tickers") or [])
        lines.append(f'"{aid}": [{label}] {title} ({tks})')

    prompt = (
        f"[투자 성향] {tendency}\n"
        f"[뉴스 목록]\n" + "\n".join(lines) + "\n\n"
        "각 기사 id를 키로 추천 이유 JSON을 작성하세요."
    )
    try:
        raw = gemini_generate_content(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=prompt,
            model=settings.gemini_summary_model,
            temperature=0.4,
            request_label="reco_reason",
        ).strip()
    except Exception as exc:
        logger.error("[추천이유] 생성 실패: %s", exc)
        return {}

    clean = raw
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning("[추천이유] JSON 파싱 실패")
        return {}

    return {
        aid: str(reason)[:60]
        for aid, reason in parsed.items()
        if aid in articles and reason
    }


def generate_reasons(article_ids: list[str], tendency: str | None = None) -> dict[str, str]:
    """(기사 id 목록, 성향) → {기사id: 추천 이유}. 캐시 우선, 누락분만 일괄 생성."""
    settings = get_settings()
    tendency = tendency or "탐색형 투자자"
    ids = [str(a) for a in (article_ids or [])][:_MAX_PER_CALL]
    if not ids:
        return {}

    cached = _get_cached(ids, tendency, settings)
    missing = [i for i in ids if i not in cached]
    if missing:
        articles = _fetch_articles(missing, settings)
        articles = {i: articles[i] for i in missing if i in articles}
        if articles:
            fresh = _generate_missing(articles, tendency, settings)
            if fresh:
                try:
                    _save(fresh, tendency, settings)
                except Exception as exc:
                    logger.warning("[추천이유] 캐시 저장 실패: %s", exc)
                cached.update(fresh)

    return {i: cached[i] for i in ids if i in cached}
