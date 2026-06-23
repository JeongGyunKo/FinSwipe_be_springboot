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
    '  "summary_3lines": [\n'
    '    "이 뉴스가 투자자에게 갖는 핵심 의미를 친근한 설명체 한국어 완성 문장으로.",\n'
    '    "주가에 영향을 줄 수 있는 핵심 리스크 또는 기회를 자연스러운 한국어 문장으로.",\n'
    '    "다음에 주목해야 할 체크포인트나 트리거를 부드러운 어투로."\n'
    '  ],\n'
    '  "sentiment_reason": "이 기사의 감성이 해당 레이블로 나온 핵심 이유 1~2문장 (투자자 관점, 친근하고 부드러운 설명체 한국어).",\n'
    '  "event_category": "earnings|guidance|analyst|product|ma|macro|regulatory|other 중 하나"\n'
    "}\n\n"
    "규칙:\n"
    "- headline_ko: '~했다' 체 기사 어미. 헤드라인 원문 반복 금지.\n"
    "- summary_3lines: 정확히 3개의 완성된 한국어 문장. 기사에 없는 수치·사실 창작 금지. "
    "'-인 점이 주목돼요', '-가능성이 있어요', '-지켜봐야 할 것 같아요' 같은 부드러운 어미 권장. "
    "헤드라인 반복 금지. 각 항목은 독립된 완성 문장.\n"
    "- sentiment_reason: 구체적인 수치나 이벤트는 언급하되, 친구에게 말하듯 따뜻하고 부드러운 설명체로. "
    "'-인 것 같아요', '-보여요', '-주목할 만해요', '-볼 필요가 있어요' 같은 어미 사용. "
    "'-분석됩니다', '-나타냅니다', '-드러내고 있습니다', '-주요 원인입니다', '-견인했습니다' 같은 딱딱한 기사체 금지. "
    "설명 문장만 출력.\n"
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

    summary_raw = data.get("summary_3lines") or []
    summary_lines = [str(s).strip() for s in summary_raw if isinstance(s, str) and str(s).strip()][:3]

    return {
        "headline_ko": data.get("headline_ko", "").strip() or None,
        "summary_3lines": summary_lines if len(summary_lines) == 3 else [],
        "sentiment_reason": data.get("sentiment_reason", "").strip() or None,
        "event_category": event_cat,
    }
