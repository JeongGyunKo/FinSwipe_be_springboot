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
    "당신은 주식을 보유한 친구에게 뉴스를 설명해주는 친근한 금융 조언자입니다. "
    "FinBERT 감성 분석 결과를 투자자가 쉽게 이해할 수 있도록 따뜻하고 부드러운 설명체 한국어로 설명합니다. "
    "'-인 것 같아요', '-보여요', '-주목할 만해요', '-볼 필요가 있어요', '-관건이 될 것 같아요' 같은 자연스러운 말투를 사용하세요. "
    "'-했다', '-것으로 판단된다', '-예상된다', '-분석된다' 같은 딱딱한 기사체 말투는 피하세요."
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
        f"이 기사의 감성이 '{label_ko}'로 분석된 핵심 이유를 1~2문장으로 설명해주세요. "
        f"구체적인 수치나 이벤트가 있으면 자연스럽게 언급하고, "
        f"친구에게 말하듯 부드럽고 따뜻한 설명체로 써주세요. "
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
