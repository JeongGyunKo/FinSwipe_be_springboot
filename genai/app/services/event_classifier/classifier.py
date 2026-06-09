from __future__ import annotations

import logging
import re

from app.services.gemini import gemini_generate_content, gemini_is_enabled

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = frozenset({
    "earnings", "guidance", "analyst", "product", "ma", "macro", "regulatory", "other",
})

_CATEGORY_PATTERN = re.compile(
    r"\b(earnings|guidance|analyst|product|ma|macro|regulatory|other)\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "You are a financial news event classifier. "
    "Given a news article headline and the first paragraph, "
    "return exactly one category from this list:\n"
    "- earnings: quarterly/annual results, EPS, revenue, profit beat/miss\n"
    "- guidance: forward guidance, outlook changes, raised/lowered forecasts\n"
    "- analyst: analyst upgrades/downgrades, price target changes, ratings\n"
    "- product: product/service launches, partnerships, deals, contracts\n"
    "- ma: mergers, acquisitions, buyouts, divestitures, spinoffs\n"
    "- macro: interest rates, inflation, employment, GDP, central bank policy\n"
    "- regulatory: regulations, lawsuits, FDA approvals, SEC actions, sanctions\n"
    "- other: anything not clearly covered above\n\n"
    "Return ONLY the single category name in lowercase. No explanation, no punctuation."
)


def classify_event_category(
    title: str,
    article_text: str,
) -> str | None:
    """헤드라인 + 본문 첫 단락으로 이벤트 카테고리 분류. 실패 시 None 반환."""
    if not gemini_is_enabled():
        return None

    excerpt = _build_excerpt(article_text)
    if not title.strip() and not excerpt.strip():
        return None

    try:
        raw = gemini_generate_content(
            model="gemini-2.5-flash-lite",
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"Headline: {title.strip()}\n\nArticle:\n{excerpt}",
            temperature=0.0,
            request_label="event_category_classification",
        )
    except Exception:
        logger.exception("[이벤트 분류] Gemini 호출 실패")
        return None

    return _parse_category(raw)


def _build_excerpt(article_text: str) -> str:
    normalized = " ".join(article_text.split())
    return normalized[:800]


def _parse_category(raw: str) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in _VALID_CATEGORIES:
        return cleaned
    match = _CATEGORY_PATTERN.search(cleaned)
    if match:
        return match.group(1).lower()
    return None
