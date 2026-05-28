from __future__ import annotations

from app.schemas.enrichment import LocalizedArticleContent
from app.schemas.storage import AnalysisOutcome, AnalysisStatus
from app.services import payload_builder as payload_builder_package
from app.services.payload_builder import builder as builder_module


def test_localized_content_uses_limited_article_excerpt(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    def _fake_build_localized_content(**kwargs):
        captured["content_text"] = kwargs.get("content_text")
        return LocalizedArticleContent(
            language="ko",
            title="localized title",
            content="localized content",
            summary_3lines=[],
            xai=None,
            sentiment_label=None,
            ticker_box_labels={},
        )

    monkeypatch.setenv("GENAI_LOCALIZED_CONTENT_CHAR_LIMIT", "80")
    monkeypatch.setattr(builder_module, "build_localized_content", _fake_build_localized_content)

    cleaned_text = (
        "Revenue grew 12% as management described stable demand across enterprise customers. "
        "The remaining article contains additional licensed paragraphs that should not be sent "
        "as full localized UI content."
    )

    payload_builder_package.build_enrichment_storage_payload(
        news_id="news-1",
        title="Company reports results",
        link="https://example.com/news-1",
        analysis_status=AnalysisStatus.COMPLETED,
        analysis_outcome=AnalysisOutcome.SUCCESS,
        stage_statuses=[],
        cleaned_text=cleaned_text,
        summary_3lines=[],
    )

    assert captured["content_text"] == (
        "Revenue grew 12% as management described stable demand across enterprise"
    )
    assert len(captured["content_text"] or "") <= 80