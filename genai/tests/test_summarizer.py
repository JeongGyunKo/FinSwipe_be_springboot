from __future__ import annotations

from app.services.summarizer import summarize_to_three_lines


def test_summarizer_returns_empty_lines_when_gemini_is_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    article_text = (
        "The company reported quarterly revenue of $12.4 billion, up 8% from a year earlier. "
        "Management said cloud demand remained strong and raised its full-year outlook. "
        "Operating margin narrowed as the company increased AI infrastructure spending. "
        "Shares rose in after-hours trading after the results were released."
    )

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=article_text,
    )

    assert summary == ["", "", ""]


def test_summarizer_returns_empty_lines_when_gemini_fails(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def _raise_error(*args, **kwargs):
        raise RuntimeError("gemini unavailable")

    monkeypatch.setattr("app.services.gemini.client.requests.post", _raise_error)

    article_text = (
        "Oil prices resumed their rise because of the war with Iran, but U.S. stocks held steadier this time around. "
        "The S&P 500 rose 0.2% Tuesday and added to its gain from the day before, which was its biggest since the war began. "
        "The Dow Jones Industrial Average climbed 0.1%, and the Nasdaq composite gained 0.5%."
    )

    summary = summarize_to_three_lines(
        title="Oil prices rise while U.S. stocks stay steadier",
        article_text=article_text,
    )

    assert summary == ["", "", ""]