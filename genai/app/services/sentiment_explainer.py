from __future__ import annotations

import logging

from app.core import get_settings

logger = logging.getLogger(__name__)

_LABEL_KO = {
    "positive": "긍정적",
    "negative": "부정적",
    "neutral": "중립적",
    "mixed": "혼재된",
}

_SYSTEM_PROMPT = (
    "당신은 금융 뉴스 분석 전문가입니다. "
    "FinBERT 감성 분석 결과를 투자자가 이해할 수 있도록 한국어로 설명합니다."
)


def explain_sentiment_reason(
    *,
    title: str,
    article_text: str,
    sentiment_label: str,
    sentiment_score: float,
) -> str | None:
    """Return a 1-2 sentence Korean explanation of why this article received its sentiment score."""
    from app.services.gemini.client import gemini_generate_content

    settings = get_settings()
    if not settings.gemini_api_key:
        return None

    label_ko = _LABEL_KO.get(sentiment_label.lower(), sentiment_label)
    excerpt = article_text[:600].strip()

    user_prompt = (
        f"뉴스 제목: {title}\n"
        f"감성 분석 결과: {label_ko} (점수: {sentiment_score:.1f})\n"
        f"기사 내용:\n{excerpt}\n\n"
        f"이 기사의 감성이 '{label_ko}'로 분석된 핵심 이유를 투자자 관점에서 "
        f"1~2문장으로 설명해주세요. 구체적인 수치나 이벤트를 언급하면 좋습니다. "
        f"설명 문장만 출력하고 다른 텍스트는 포함하지 마세요."
    )

    try:
        result = gemini_generate_content(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.gemini_summary_model,
            temperature=0.2,
            request_label="sentiment_explain",
        )
        return result.strip() or None
    except Exception as exc:
        logger.warning("감성 설명 생성 실패: %s", exc)
        return None
