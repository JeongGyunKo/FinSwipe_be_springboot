from __future__ import annotations

from app.schemas.xai import XAIContributionDirection
from app.services.xai.lime_explainer import (
    SentenceSpan,
    _build_highlights,
    _extract_keyword_spans,
    _split_sentence_spans,
)


def test_split_sentence_spans_tracks_offsets_in_order() -> None:
    text = "Revenue rose. Margins improved. Outlook stayed firm."

    spans = _split_sentence_spans(text)

    assert len(spans) == 3
    assert spans[0].text == "Revenue rose."
    assert spans[0].start_char == 0
    assert spans[0].end_char == len("Revenue rose.")
    assert text[spans[1].start_char:spans[1].end_char] == "Margins improved."
    assert text[spans[2].start_char:spans[2].end_char] == "Outlook stayed firm."


def test_build_highlights_includes_start_and_end_offsets() -> None:
    lookup = {
        "s0": SentenceSpan(
            index=0,
            text="Revenue rose.",
            start_char=0,
            end_char=13,
        ),
        "s1": SentenceSpan(
            index=1,
            text="Margins improved.",
            start_char=14,
            end_char=31,
        ),
    }

    highlights = _build_highlights(
        explanation_items=[("s0", 0.25), ("s1", -0.1)],
        sentence_lookup=lookup,
    )

    assert len(highlights) == 2
    assert highlights[0].text_snippet == "Revenue rose."
    assert highlights[0].start_char == 0
    assert highlights[0].end_char == 13
    assert highlights[0].contribution_direction == XAIContributionDirection.POSITIVE
    assert highlights[1].start_char == 14
    assert highlights[1].end_char == 31
    assert highlights[1].contribution_direction == XAIContributionDirection.NEGATIVE


def test_extract_keyword_spans_preserves_global_offsets() -> None:
    sentence_span = SentenceSpan(
        index=0,
        text="Airline stocks climbed after Delta raised forecasts.",
        start_char=100,
        end_char=152,
    )

    keyword_spans = _extract_keyword_spans(
        sentence_span=sentence_span,
        sentence_importance=0.5,
    )

    assert keyword_spans
    assert all(span.start_char >= 100 for span in keyword_spans)
    assert all(span.end_char > span.start_char for span in keyword_spans)
    extracted_tokens = {span.text_snippet for span in keyword_spans}
    assert "Airline" in extracted_tokens or "Delta" in extracted_tokens