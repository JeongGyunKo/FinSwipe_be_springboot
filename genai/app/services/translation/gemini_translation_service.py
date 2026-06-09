from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from app.core import get_settings
from app.schemas.enrichment import (
    LocalizedArticleContent,
    SentimentLabel,
    SummaryLine,
    XAIHighlightItem,
    XAIPayload,
)
from app.services.gemini import gemini_generate_content, gemini_is_enabled

logger = logging.getLogger(__name__)

_FINANCE_TOKEN_PATTERN = re.compile(
    r"\b(?:EPS|YoY|QoQ|P/E|EBITDA|ROI|ROE|CAGR|FCF|AI|IPO)\b"
)
_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:[$€£¥]?\d[\d,]*(?:\.\d+)?%?|\d+(?:\.\d+)?x)(?![A-Za-z])"
)
_HANGUL_PATTERN = re.compile(r"[가-힣]")
_LETTER_PATTERN = re.compile(r"[A-Za-z가-힣]")
_DISALLOWED_TRANSLATION_SCRIPT_PATTERN = re.compile(r"[\u0900-\u097F\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF]")
_MASK_PLACEHOLDER_INDEX_PATTERN = re.compile(r"ZXQKEEP(\d+)ZXQ")
_MASK_PLACEHOLDER_LOOSE_PATTERN = re.compile(
    r"z\s*x\s*q\s*keep\s*(\d+)(?:\s*z\s*x\s*q)?",
    re.IGNORECASE,
)
_CODE_FENCE_PATTERN = re.compile(r"^```(?:json|text)?\s*|\s*```$", re.IGNORECASE)

_SENTIMENT_LABELS_KO = {
    SentimentLabel.BULLISH: "강세",
    SentimentLabel.BEARISH: "약세",
    SentimentLabel.NEUTRAL: "중립",
    SentimentLabel.MIXED: "혼합",
}

_TICKER_BOX_LABELS_KO = {
    "revenue": "매출",
    "net_income": "순이익",
    "operating_income": "영업이익",
    "guidance": "가이던스",
    "target_price": "목표주가",
    "dividend": "배당",
    "eps": "EPS",
    "yoy": "YoY",
    "qoq": "QoQ",
    "market_cap": "시가총액",
    "pe_ratio": "PER",
}


@dataclass(frozen=True, slots=True)
class _MaskedText:
    text: str
    replacements: dict[str, str]


@dataclass(frozen=True, slots=True)
class _TranslationTask:
    key: str
    text: str


def build_localized_content(
    *,
    title: str,
    content_text: str | None = None,
    summary_3lines: list[SummaryLine],
    xai: XAIPayload | None,
    sentiment_label: SentimentLabel | None,
    tickers: list[str] | None = None,
    xai_highlight_limit: int | None = None,
    allow_gemini: bool = True,
) -> LocalizedArticleContent | None:
    limited_xai = _limit_xai_payload(xai, highlight_limit=xai_highlight_limit)
    translations = _translate_localized_payload(
        title=title,
        content_text=content_text,
        summary_3lines=summary_3lines,
        xai=limited_xai,
        tickers=tickers,
        allow_gemini=allow_gemini,
    )
    if translations is None:
        logger.warning("Gemini translation unavailable; returning empty localized payload.")
        return None

    translated_title = translations.get("title", "").strip()
    if not translated_title:
        logger.warning("Gemini translation returned an empty localized title.")
        return None

    translated_summary: list[SummaryLine] = []
    for line in summary_3lines:
        translated_text = translations.get(f"summary_{line.line_number}", "").strip()
        if translated_text:
            translated_summary.append(SummaryLine(line_number=line.line_number, text=translated_text))

    translated_xai = _translate_xai_payload(limited_xai, translations=translations)
    translated_content = translations.get("content", "").strip() or None

    return LocalizedArticleContent(
        language="ko",
        title=translated_title,
        content=translated_content,
        summary_3lines=translated_summary,
        xai=translated_xai,
        sentiment_label=_SENTIMENT_LABELS_KO.get(sentiment_label),
        ticker_box_labels=dict(_TICKER_BOX_LABELS_KO),
    )


def _limit_xai_payload(
    payload: XAIPayload | None,
    *,
    highlight_limit: int | None,
) -> XAIPayload | None:
    if payload is None or highlight_limit is None or highlight_limit < 0:
        return payload
    return XAIPayload(
        explanation=payload.explanation,
        highlights=payload.highlights[:highlight_limit],
    )


def _translate_xai_payload(payload: XAIPayload | None, *, translations: dict[str, str]) -> XAIPayload | None:
    if payload is None:
        return None

    explanation = translations.get("xai_explanation", "").strip()
    if not explanation:
        return None

    translated_highlights: list[XAIHighlightItem] = []
    for index, item in enumerate(payload.highlights):
        excerpt = translations.get(f"xai_highlight_{index + 1}", "").strip()
        if not excerpt:
            return None
        detail_key = f"xai_detail_{index + 1}"
        detail_value = translations.get(detail_key, "").strip()
        translated_highlights.append(
            XAIHighlightItem(
                excerpt=excerpt,
                relevance_score=item.relevance_score,
                explanation=(detail_value if item.explanation and detail_value else None),
                sentiment_signal=item.sentiment_signal,
                start_char=None,
                end_char=None,
            )
        )

    return XAIPayload(
        explanation=explanation,
        highlights=translated_highlights,
    )


def _translate_localized_payload(
    *,
    title: str,
    content_text: str | None,
    summary_3lines: list[SummaryLine],
    xai: XAIPayload | None,
    tickers: list[str] | None,
    allow_gemini: bool,
) -> dict[str, str] | None:
    tasks = _build_translation_tasks(
        title=title,
        content_text=content_text,
        summary_3lines=summary_3lines,
        xai=xai,
    )
    if not allow_gemini or not gemini_is_enabled():
        return None

    try:
        return _translate_tasks(tasks, tickers=tickers)
    except Exception:
        logger.exception("Gemini translation failed.")
        return None


def _build_translation_tasks(
    *,
    title: str,
    content_text: str | None,
    summary_3lines: list[SummaryLine],
    xai: XAIPayload | None,
) -> list[_TranslationTask]:
    tasks: list[_TranslationTask] = [_TranslationTask(key="title", text=title)]
    tasks.extend(
        _TranslationTask(key=f"summary_{line.line_number}", text=line.text)
        for line in summary_3lines
    )
    if content_text and content_text.strip():
        tasks.append(_TranslationTask(key="content", text=content_text))
    if xai is not None:
        tasks.append(_TranslationTask(key="xai_explanation", text=xai.explanation))
        for index, item in enumerate(xai.highlights, start=1):
            tasks.append(_TranslationTask(key=f"xai_highlight_{index}", text=item.excerpt))
            if item.explanation:
                tasks.append(_TranslationTask(key=f"xai_detail_{index}", text=item.explanation))
    return tasks


def _translate_tasks(
    tasks: list[_TranslationTask],
    *,
    tickers: list[str] | None,
) -> dict[str, str]:
    results = {task.key: "" for task in tasks}
    prepared_tasks = [
        _TranslationTask(
            key=task.key,
            text=_prepare_translation_input(task.text.strip(), char_limit=get_settings().gemini_translation_char_limit),
        )
        for task in tasks
        if task.text.strip() and not _looks_already_korean(task.text)
    ]
    for task in tasks:
        original = task.text.strip()
        if original and _looks_already_korean(original):
            results[task.key] = original

    if not prepared_tasks:
        return results

    _merge_translations_for_tasks(
        results=results,
        tasks=prepared_tasks,
        tickers=tickers,
        request_label="translate_localized_payload",
    )
    missing_keys = [task.key for task in prepared_tasks if not results.get(task.key, "").strip()]
    if missing_keys:
        retry_tasks = [task for task in prepared_tasks if task.key in set(missing_keys)]
        _merge_translations_for_tasks(
            results=results,
            tasks=retry_tasks,
            tickers=tickers,
            request_label="translate_localized_payload_repair",
        )
        missing_keys = [task.key for task in prepared_tasks if not results.get(task.key, "").strip()]
        logger.warning(
            "Gemini translation left some fields empty after validation.",
            extra={
                "missing_keys": ",".join(missing_keys),
                "prepared_task_count": len(prepared_tasks),
            },
        )
    return results


def _merge_translations_for_tasks(
    *,
    results: dict[str, str],
    tasks: list[_TranslationTask],
    tickers: list[str] | None,
    request_label: str,
) -> None:
    if not tasks:
        return
    batch_payload = _build_translation_batch_payload(tasks)
    masked = _mask_text(batch_payload, tickers=tickers)
    translated = _cached_translation_batch_completion(
        get_settings().gemini_api_base_url,
        get_settings().gemini_translation_model,
        masked.text,
        request_label,
    )
    unmasked = _unmask_text(translated, masked.replacements)
    parsed = _parse_translation_batch_output(unmasked, tasks)
    for task in tasks:
        translated_text = parsed.get(task.key, "")
        if "|||" in translated_text:
            continue
        polished = _polish_korean_financial_text(translated_text)
        if _is_usable_korean_translation(polished):
            results[task.key] = polished


def _build_translation_batch_payload(tasks: Iterable[_TranslationTask]) -> str:
    return "\n".join(f"{task.key}|||{task.text}" for task in tasks)


def _parse_translation_batch_output(
    output: str,
    tasks: list[_TranslationTask],
) -> dict[str, str]:
    normalized_output = _strip_code_fence(output)
    json_parsed = _parse_translation_json_output(normalized_output, tasks)
    if json_parsed:
        return json_parsed

    span_parsed = _parse_translation_key_spans(normalized_output, tasks)
    if span_parsed:
        return span_parsed

    parsed: dict[str, str] = {}
    valid_keys = {task.key for task in tasks}
    for raw_line in normalized_output.splitlines():
        line = raw_line.strip()
        if not line or "|||" not in line:
            continue
        key, text = line.split("|||", 1)
        normalized_key = key.strip()
        normalized_text = text.strip()
        if normalized_key in valid_keys and normalized_text:
            parsed[normalized_key] = normalized_text
    return parsed


def _strip_code_fence(text: str) -> str:
    return _CODE_FENCE_PATTERN.sub("", text.strip())


def _parse_translation_json_output(
    output: str,
    tasks: list[_TranslationTask],
) -> dict[str, str]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    valid_keys = {task.key for task in tasks}
    parsed: dict[str, str] = {}
    for key, value in payload.items():
        if key not in valid_keys or not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized:
            parsed[key] = normalized
    return parsed


def _parse_translation_key_spans(
    output: str,
    tasks: list[_TranslationTask],
) -> dict[str, str]:
    keys = [task.key for task in tasks]
    if not keys:
        return {}
    key_group = "|".join(re.escape(key) for key in keys)
    pattern = re.compile(
        rf"(?P<key>{key_group})\s*\|\|\|\s*(?P<text>.*?)(?=(?:{key_group})\s*\|\|\||\s+[A-Za-z0-9_]+\s*\|\|\||\Z)",
        re.DOTALL,
    )
    parsed: dict[str, str] = {}
    for match in pattern.finditer(output):
        key = match.group("key").strip()
        text = " ".join(match.group("text").strip().splitlines()).strip()
        if text:
            parsed[key] = text
    return parsed


def _looks_already_korean(text: str) -> bool:
    letters = _LETTER_PATTERN.findall(text)
    if not letters:
        return False

    hangul_count = len(_HANGUL_PATTERN.findall(text))
    return hangul_count / len(letters) >= 0.35


def _is_usable_korean_translation(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    disallowed_count = len(_DISALLOWED_TRANSLATION_SCRIPT_PATTERN.findall(normalized))
    if disallowed_count > 0 and (disallowed_count / max(1, len(normalized))) > 0.20:
        return False
    letters = _LETTER_PATTERN.findall(normalized)
    if not letters:
        return False
    hangul_count = len(_HANGUL_PATTERN.findall(normalized))
    # Keep translations that are mostly Korean while still allowing finance terms and tickers.
    return hangul_count / len(letters) >= 0.18


def _mask_text(text: str, *, tickers: list[str] | None) -> _MaskedText:
    replacements: dict[str, str] = {}
    token_to_placeholder: dict[str, str] = {}
    protected_tokens = [
        token
        for token in sorted(
            {
                *(ticker.strip() for ticker in (tickers or []) if ticker and ticker.strip()),
                *(_FINANCE_TOKEN_PATTERN.findall(text)),
                *(_NUMBER_PATTERN.findall(text)),
            },
            key=len,
            reverse=True,
        )
        if token
    ]
    if not protected_tokens:
        return _MaskedText(text=text, replacements={})

    token_pattern = re.compile("|".join(re.escape(token) for token in protected_tokens))

    def _replace_token(match: re.Match[str]) -> str:
        token = match.group(0)
        placeholder = token_to_placeholder.get(token)
        if placeholder is None:
            placeholder = f"ZXQKEEP{len(token_to_placeholder)}ZXQ"
            token_to_placeholder[token] = placeholder
            replacements[placeholder] = token
        return placeholder

    masked_lines: list[str] = []
    for line in text.splitlines():
        if "|||" not in line:
            masked_lines.append(token_pattern.sub(_replace_token, line))
            continue
        key, payload = line.split("|||", 1)
        masked_lines.append(f"{key}|||{token_pattern.sub(_replace_token, payload)}")

    return _MaskedText(text="\n".join(masked_lines), replacements=replacements)


def _unmask_text(text: str, replacements: dict[str, str]) -> str:
    unmasked = text
    for placeholder, token in replacements.items():
        unmasked = unmasked.replace(placeholder, token)
    index_to_token = _build_mask_index_token_map(replacements)
    if index_to_token:
        unmasked = _MASK_PLACEHOLDER_LOOSE_PATTERN.sub(
            lambda match: index_to_token.get(match.group(1), match.group(0)),
            unmasked,
        )
    return unmasked


def _build_mask_index_token_map(replacements: dict[str, str]) -> dict[str, str]:
    index_to_token: dict[str, str] = {}
    for placeholder, token in replacements.items():
        match = _MASK_PLACEHOLDER_INDEX_PATTERN.fullmatch(placeholder)
        if match is None:
            continue
        index_to_token[match.group(1)] = token
    return index_to_token


@lru_cache(maxsize=256)
def _cached_translation_batch_completion(
    base_url: str,
    model: str,
    masked_payload: str,
    request_label: str,
) -> str:
    del base_url
    return gemini_generate_content(
        model=model,
        system_prompt=(
            "You are a Korean financial news translation engine for a stock-news app. "
            "Translate each tagged record into polished Korean financial news copy while preserving the original facts exactly. "
            "Output Korean only. Never use Hindi, Chinese, Japanese, or mixed-language sentences. "
            "English may remain only for ticker symbols, company or product names, finance abbreviations, and placeholders. "
            "Input lines are formatted as KEY|||TEXT. "
            "Return the same number of lines in the exact same KEY|||TEXT format. "
            "Keep every KEY unchanged, in the same order, with no missing, renamed, merged, or additional keys. "
            "Translate only the TEXT portion. "
            "Do not output JSON, markdown, bullets, quotes, explanations, comments, labels, or extra lines. "
            "Use concise Korean financial 기사체 and avoid literal translation. "
            "Prefer endings such as '-했다', '-밝혔다', '-기록했다', '-상회했다', '-밑돌았다', '-상향했다', and '-하향했다'. "
            "Avoid conversational endings such as '-라고 합니다', '-인 것 같습니다', or '-할 수도 있습니다'. "
            "Convert common market phrases naturally: 'shares rose/jumped/surged' to '주가가 상승/급등했다', "
            "'shares fell/slid/dropped/tumbled' to '주가가 하락/급락했다', "
            "'beat estimates' to '시장 예상치를 상회했다', "
            "'missed expectations' to '시장 예상치를 밑돌았다', "
            "'raised guidance' to '가이던스를 상향했다', "
            "'lowered guidance' to '가이던스를 하향했다', "
            "'maintained guidance' to '가이던스를 유지했다', "
            "'price target' to '목표주가', "
            "'upgrade' to '투자의견 상향', and "
            "'downgrade' to '투자의견 하향'. "
            "Use standard Korean finance terms such as '시장 예상치', '전년 대비', '전분기 대비', '가이던스', '마진', '영업이익', '순이익', '잉여현금흐름', '주주환원', '자사주 매입', '배당', '경영진', and '목표주가' when appropriate. "
            "Keep placeholders unchanged. "
            "Keep numbers, percentages, dates, currencies, quarters, ticker symbols, and finance abbreviations exactly as written. "
            "Do not convert units, recalculate figures, round numbers, or infer missing comparisons. "
            "Keep company names and product names recognizable; do not translate ticker symbols. "
            "Do not add investment advice, buy/sell recommendations, causal claims, forecasts, or facts that are not present in the input. "
            "Do not exaggerate tone or turn neutral wording into positive or negative judgment. "
            "Before answering, silently verify: same KEY count and order, Korean-only translated text, preserved numbers/tickers/placeholders, no added facts, no extra lines. "
            "Do not print the verification. Return only KEY|||TEXT lines."
        ),
        user_prompt=masked_payload,
        temperature=0.0,
        request_label=request_label,
    )


def _prepare_translation_input(text: str, *, char_limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= char_limit:
        return normalized

    truncated = normalized[:char_limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return truncated or normalized[:char_limit]


def translate_titles(titles: list[str], *, tickers: list[str] | None = None) -> list[str | None]:
    """영어 헤드라인 목록을 한국어로 번역. 번역 실패 항목은 None 반환."""
    valid_indices = [i for i, t in enumerate(titles) if t and t.strip()]
    if not valid_indices or not gemini_is_enabled():
        return [None] * len(titles)
    tasks = [_TranslationTask(key=f"t{i}", text=titles[i]) for i in valid_indices]
    try:
        translations = _translate_tasks(tasks, tickers=tickers)
    except Exception:
        logger.exception("Headline batch translation failed.")
        return [None] * len(titles)
    result: list[str | None] = [None] * len(titles)
    for i in valid_indices:
        result[i] = translations.get(f"t{i}") or None
    return result


def _polish_korean_financial_text(text: str) -> str:
    polished = text.strip()
    replacements = (
        ("매니저들", "경영진"),
        ("매니저들은", "경영진은"),
        ("매니저는", "경영진은"),
        ("관리진", "경영진"),
        ("전망을 높였다고", "가이던스를 상향했다고"),
        ("했다고 합니다.", "했다고 밝혔다."),
        ("라고 합니다.", "라고 밝혔다."),
        ("라고 말했다.", "라고 밝혔다."),
        ("말했습니다.", "밝혔다."),
        ("말했다.", "밝혔다."),
        ("전망을 높였다", "가이던스를 상향했다"),
        ("강력하게 유지", "견조했다"),
        ("향상되었다고 합니다.", "개선됐다."),
        ("향상되었다.", "개선됐다."),
    )
    for source, target in replacements:
        polished = polished.replace(source, target)
    return polished