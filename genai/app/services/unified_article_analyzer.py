"""
기사 1건에 대해 Gemini를 1회만 호출하여 필요한 모든 정보를 생성.
headline_ko / summary_ko 3줄 / sentiment_reason / event_category
"""
from __future__ import annotations

import json
import logging
import re

from app.core import get_settings
from app.services.gemini import gemini_generate_content, gemini_is_enabled

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = frozenset({
    "earnings", "guidance", "analyst", "product", "ma", "macro", "regulatory", "other",
})

_CODE_FENCE_PATTERN = re.compile(r"^```(?:json|text)?\s*|\s*```$", re.IGNORECASE)

_SYSTEM_PROMPT = (
    "당신은 금융 뉴스 분석 전문가입니다. 영문 금융 뉴스 기사를 분석해 아래 JSON만 반환하세요.\n\n"
    "{\n"
    '  "headline_ko": "영문 헤드라인의 한국어 번역 (간결한 금융 기사체, 예: \'엔비디아, 2분기 매출 시장 예상치 상회\').",\n'
    '  "summary_1": "이 뉴스가 투자자에게 의미하는 것 — 완전한 한국어 문장, 따뜻한 설명체.",\n'
    '  "summary_2": "주가에 영향을 줄 핵심 리스크 또는 기회 — 완전한 한국어 문장.",\n'
    '  "summary_3": "다음에 지켜볼 체크포인트 또는 트리거 — 완전한 한국어 문장.",\n'
    '  "sentiment_reason": "이 기사의 감성이 해당 레이블로 분석된 핵심 이유 1~2문장 (투자자 관점, 한국어).",\n'
    '  "event_category": "earnings|guidance|analyst|product|ma|macro|regulatory|other 중 하나"\n'
    "}\n\n"
    "규칙:\n"
    "- headline_ko: '~했다' 체 기사 어미. 헤드라인 원문 반복 금지.\n"
    "- summary_1~3: '-인 점이 주목돼요', '-가능성이 있어요', '-지켜봐야 할 것 같아요' 같은 부드러운 어미. "
    "숫자·날짜·티커·회사명은 원문 그대로 보존. 사실을 창작하지 말 것.\n"
    "- sentiment_reason: 구체적인 수치나 이벤트 언급. 설명 문장만 출력.\n"
    "- event_category: earnings=실적/EPS/매출, guidance=전망치 상하향, analyst=목표주가/투자의견, "
    "product=신제품/파트너십, ma=인수합병, macro=금리/GDP/중앙은행, regulatory=규제/소송/FDA, other=기타\n"
    "JSON 외 다른 텍스트는 일절 출력하지 마세요."
)


def analyze_article_unified(
    *,
    title: str,
    article_text: str,
    sentiment_label: str,
    sentiment_score: float,
) -> dict:
    """
    1번 Gemini 호출로 카드에 필요한 모든 정보 반환.
    keys: headline_ko, summary_1, summary_2, summary_3, sentiment_reason, event_category
    실패한 필드는 None.
    """
    if not gemini_is_enabled():
        return {}

    settings = get_settings()
    label_ko_map = {
        "positive": "긍정적",
        "negative": "부정적",
        "neutral": "중립적",
        "mixed": "혼재된",
    }
    label_ko = label_ko_map.get(sentiment_label.lower(), sentiment_label)
    excerpt = article_text[:2000].strip()

    user_prompt = (
        f"헤드라인: {title}\n"
        f"감성 분석 결과: {label_ko} (점수: {sentiment_score:.1f}/100)\n\n"
        f"기사 본문:\n{excerpt}"
    )

    try:
        raw = gemini_generate_content(
            model=settings.gemini_summary_model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            request_label="unified_article_analysis",
        )
    except Exception:
        logger.exception("[통합 분석] Gemini 호출 실패")
        return {}

    return _parse_output(raw)


def _parse_output(raw: str) -> dict:
    cleaned = _CODE_FENCE_PATTERN.sub("", raw.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("[통합 분석] JSON 파싱 실패: %.200s", cleaned)
        return {}

    event_cat = data.get("event_category", "").strip().lower()
    if event_cat not in _VALID_CATEGORIES:
        event_cat = None

    return {
        "headline_ko": data.get("headline_ko", "").strip() or None,
        "summary_1": data.get("summary_1", "").strip() or None,
        "summary_2": data.get("summary_2", "").strip() or None,
        "summary_3": data.get("summary_3", "").strip() or None,
        "sentiment_reason": data.get("sentiment_reason", "").strip() or None,
        "event_category": event_cat,
    }
