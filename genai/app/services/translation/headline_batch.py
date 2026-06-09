from __future__ import annotations

from app.services.translation.gemini_translation_service import translate_titles


def translate_headlines_batch(items: list) -> list[dict]:
    """헤드라인 전용 경량 번역 — retry_count 무관, headline_ko만 채움."""
    if not items:
        return []
    headlines = [item.headline for item in items]
    translated = translate_titles(headlines)
    return [
        {"id": item.id, "headline_ko": ko}
        for item, ko in zip(items, translated)
    ]
