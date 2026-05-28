from __future__ import annotations

import itertools

import pytest

from app.schemas.enrichment import SummaryLine, XAIHighlightItem, XAIPayload, SentimentLabel
from app.services.translation.gemini_translation_service import (
    _cached_translation_batch_completion,
    build_localized_content,
)


def _build_response_text(*, missing_keys: set[str]) -> str:
    base = {
        "title": "애플이 가이던스를 상향했다",
        "summary_1": "매출은 12% 증가했다.",
        "summary_2": "마진은 개선됐다.",
        "summary_3": "가이던스는 상향됐다.",
        "content": "회사는 수요 개선을 근거로 연간 전망을 상향했다.",
        "xai_explanation": "강세 판단에 영향을 준 핵심 문장이다.",
        "xai_highlight_1": "가이던스 상향이 긍정 신호로 작용했다.",
    }
    lines = []
    for key, value in base.items():
        if key in missing_keys:
            lines.append(f"{key}|||")
        else:
            lines.append(f"{key}|||{value}")
    return "\n".join(lines)


@pytest.mark.parametrize(
    "missing_keys",
    [
        set(keys)
        for keys in itertools.islice(
            (
                combo
                for size in range(0, 5)
                for combo in itertools.combinations(
                    [
                        "summary_1",
                        "summary_2",
                        "summary_3",
                        "content",
                        "xai_explanation",
                        "xai_highlight_1",
                    ],
                    size,
                )
            ),
            20,
        )
    ],
)
def test_release_regression_localized_payload_respects_missing_translation_fields(
    monkeypatch, missing_keys: set[str]
) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": _build_response_text(missing_keys=missing_keys),
                                }
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr("app.services.gemini.client.requests.post", lambda *args, **kwargs: _Response())

    localized = build_localized_content(
        title="Apple raises guidance",
        content_text="The company raised annual guidance based on stronger demand.",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=XAIPayload(
            explanation="Top article snippets influencing the bullish sentiment result.",
            highlights=[
                XAIHighlightItem(
                    excerpt="Guidance was raised.",
                    relevance_score=0.8,
                    explanation=None,
                    sentiment_signal=SentimentLabel.BULLISH,
                    start_char=0,
                    end_char=19,
                )
            ],
        ),
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    assert localized is not None
    assert localized.title.strip()
    summary_by_line = {line.line_number: line.text for line in localized.summary_3lines}
    for line_number in (1, 2, 3):
        key = f"summary_{line_number}"
        if key in missing_keys:
            assert line_number not in summary_by_line
        else:
            assert summary_by_line.get(line_number, "").strip()

    if "content" in missing_keys:
        assert localized.content is None
    else:
        assert localized.content is not None and localized.content.strip()

    if "xai_explanation" in missing_keys or "xai_highlight_1" in missing_keys:
        assert localized.xai is None
    else:
        assert localized.xai is not None
        assert localized.xai.explanation.strip()
        assert localized.xai.highlights and localized.xai.highlights[0].excerpt.strip()