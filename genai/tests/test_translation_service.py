from __future__ import annotations

from app.schemas.enrichment import SummaryLine, XAIHighlightItem, XAIPayload
from app.schemas.enrichment import SentimentLabel
from app.services.translation.gemini_translation_service import _cached_translation_batch_completion
from app.services.translation.gemini_translation_service import _parse_translation_batch_output
from app.services.translation.gemini_translation_service import _polish_korean_financial_text
from app.services.translation.gemini_translation_service import _unmask_text
from app.services.translation.gemini_translation_service import _TranslationTask
from app.services.translation.gemini_translation_service import build_localized_content


def test_build_localized_content_returns_none_without_api_key(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    localized = build_localized_content(
        title="Apple raises guidance",
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

    assert localized is None


def test_build_localized_content_uses_Gemini_when_api_key_present(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "title|||애플이 가이던스를 상향했습니다\n"
                                "summary_1|||매출은 12% 증가했습니다.\n"
                                "summary_2|||마진이 개선되었습니다.\n"
                                "summary_3|||가이던스가 상향되었습니다.\n"
                                "xai_explanation|||강세 판단에 영향을 준 핵심 문장입니다.\n"
                                "xai_highlight_1|||가이던스가 상향되었습니다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    localized = build_localized_content(
        title="Apple raises guidance",
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

    assert localized.title == "애플이 가이던스를 상향했습니다"
    assert localized.summary_3lines[0].text == "매출은 12% 증가했습니다."
    assert localized.xai is not None
    assert localized.xai.explanation == "강세 판단에 영향을 준 핵심 문장입니다."
    assert localized.xai.highlights[0].excerpt == "가이던스가 상향되었습니다."
    assert localized.xai.highlights[0].start_char is None
    assert localized.xai.highlights[0].end_char is None


def test_build_localized_content_translates_article_content(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    captured_payloads: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "title|||애플이 가이던스를 상향했다\n"
                                "summary_1|||매출은 12% 증가했다.\n"
                                "summary_2|||마진은 개선됐다.\n"
                                "summary_3|||가이던스는 상향됐다.\n"
                                "content|||애플은 매출이 12% 증가했고 가이던스를 상향했다고 밝혔다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        captured_payloads.append(kwargs["json"]["contents"][0]["parts"][0]["text"])
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    localized = build_localized_content(
        title="Apple raises guidance",
        content_text="Apple said revenue grew 12% and guidance was raised.",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    assert "summary_1|||Revenue grew ZXQKEEP0ZXQ." in captured_payloads[0]
    assert "content|||Apple said revenue grew ZXQKEEP0ZXQ and guidance was raised." in captured_payloads[0]
    assert localized is not None
    assert localized.content == "애플은 매출이 12% 증가했고 가이던스를 상향했다고 밝혔다."


def test_build_localized_content_returns_none_when_gemini_is_disabled(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def _fail_post(*args, **kwargs):
        raise AssertionError("response fallback should not spend Gemini tokens")

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fail_post)

    localized = build_localized_content(
        title="Apple raises guidance",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
        allow_gemini=False,
    )

    assert localized is None


def test_build_localized_content_reuses_cached_Gemini_translations(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    calls = {"count": 0}
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            calls["count"] += 1
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "title|||애플이 가이던스를 상향했습니다\n"
                                "summary_1|||매출은 12% 증가했습니다.\n"
                                "summary_2|||마진이 개선되었습니다.\n"
                                "summary_3|||가이던스가 상향되었습니다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    kwargs = dict(
        title="Apple raises guidance",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    first = build_localized_content(**kwargs)
    second = build_localized_content(**kwargs)

    assert first.title == second.title
    assert first.summary_3lines[0].text == second.summary_3lines[0].text
    assert calls["count"] == 1


def test_build_localized_content_retries_missing_translation_keys_once(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    calls = {"count": 0}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": (
                                    "title|||애플이 가이던스를 상향했습니다\n"
                                    "summary_1|||매출은 12% 증가했습니다.\n"
                                    "summary_2|||bad english output\n"
                                    "summary_3|||가이던스가 상향되었습니다."
                                )}]
                            }
                        }
                    ]
                }
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "summary_2|||마진이 개선되었습니다."}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    localized = build_localized_content(
        title="Apple raises guidance",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    assert localized is not None
    assert localized.summary_3lines[1].text == "마진이 개선되었습니다."
    assert calls["count"] == 2


def test_build_localized_content_returns_none_when_localized_title_is_empty(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "title|||\n"
                                "summary_1|||매출은 12% 증가했다.\n"
                                "summary_2|||마진은 개선됐다.\n"
                                "summary_3|||가이던스는 상향됐다."
                            )}]
                        }
                    }
                ]
            }

    monkeypatch.setattr("app.services.gemini.client.requests.post", lambda *args, **kwargs: _Response())

    localized = build_localized_content(
        title="Apple raises guidance",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    assert localized is None


def test_build_localized_content_skips_already_korean_summary_lines(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    captured_payloads: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "title|||애플이 가이던스를 상향했습니다"}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        captured_payloads.append(kwargs["json"]["contents"][0]["parts"][0]["text"])
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    localized = build_localized_content(
        title="Apple raises guidance",
        summary_3lines=[
            SummaryLine(line_number=1, text="매출은 12% 증가했다."),
            SummaryLine(line_number=2, text="마진은 개선됐다."),
            SummaryLine(line_number=3, text="경영진은 가이던스를 상향했다."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    assert captured_payloads == ["title|||Apple raises guidance"]
    assert localized.title == "애플이 가이던스를 상향했습니다"
    assert localized.summary_3lines[0].text == "매출은 12% 증가했다."
    assert localized.summary_3lines[2].text == "경영진은 가이던스를 상향했다."


def test_polish_korean_financial_text_normalizes_literal_finance_phrases() -> None:
    polished = _polish_korean_financial_text(
        "매니저들은 올해 전망을 높였다고 합니다. 운영 마진은 향상되었다."
    )

    assert polished == "경영진은 올해 가이던스를 상향했다고 밝혔다. 운영 마진은 개선됐다."


def test_unmask_text_restores_loose_placeholder_variants() -> None:
    restored = _unmask_text(
        "회사는 ZXQ KEEP 2 zXQ 주가 흐름을 설명했다.",
        {"ZXQKEEP2ZXQ": "AAPL"},
    )
    assert restored == "회사는 AAPL 주가 흐름을 설명했다."


def test_build_localized_content_keeps_partial_summary_when_some_lines_fail(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "title|||애플이 가이던스를 상향했다\n"
                                "summary_1|||매출은 12% 증가했다\n"
                                "summary_2|||\n"
                                "summary_3|||가이던스를 상향했다"
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    localized = build_localized_content(
        title="Apple raises guidance",
        summary_3lines=[
            SummaryLine(line_number=1, text="Revenue grew 12%."),
            SummaryLine(line_number=2, text="Margins improved."),
            SummaryLine(line_number=3, text="Guidance was raised."),
        ],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    assert localized is not None
    assert localized.title == "애플이 가이던스를 상향했다"
    assert [line.line_number for line in localized.summary_3lines] == [1, 3]
    assert [line.text for line in localized.summary_3lines] == [
        "매출은 12% 증가했다",
        "가이던스를 상향했다",
    ]


def test_parse_translation_batch_output_accepts_json_payload() -> None:
    parsed = _parse_translation_batch_output(
        """```json
        {
          "title": "애플이 가이던스를 상향했다",
          "summary_1": "매출은 12% 증가했다",
          "summary_2": "마진은 개선됐다"
        }
        ```""",
        [
            _TranslationTask(key="title", text="Apple raises guidance"),
            _TranslationTask(key="summary_1", text="Revenue grew 12%"),
            _TranslationTask(key="summary_2", text="Margins improved"),
        ],
    )

    assert parsed["title"] == "애플이 가이던스를 상향했다"
    assert parsed["summary_1"] == "매출은 12% 증가했다"
    assert parsed["summary_2"] == "마진은 개선됐다"


def test_parse_translation_batch_output_accepts_single_line_key_spans() -> None:
    parsed = _parse_translation_batch_output(
        (
            "title|||애플이 가이던스를 상향했다 "
            "summary_1|||매출은 12% 증가했다 "
            "summary_2|||마진은 개선됐다"
        ),
        [
            _TranslationTask(key="title", text="Apple raises guidance"),
            _TranslationTask(key="summary_1", text="Revenue grew 12%"),
            _TranslationTask(key="summary_2", text="Margins improved"),
        ],
    )

    assert parsed["title"] == "애플이 가이던스를 상향했다"
    assert parsed["summary_1"] == "매출은 12% 증가했다"
    assert parsed["summary_2"] == "마진은 개선됐다"


def test_translation_prompt_includes_market_phrase_rules(monkeypatch) -> None:
    _cached_translation_batch_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "title|||애플 주가가 급등했다"}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        captured.update(kwargs.get("json", {}))
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    build_localized_content(
        title="Apple shares jumped",
        summary_3lines=[],
        xai=None,
        sentiment_label=SentimentLabel.BULLISH,
        tickers=["AAPL"],
    )

    request_text = str(captured)
    assert "'shares rose/jumped/surged' to '주가가 상승/급등했다'" in request_text
    assert "'beat estimates' to '시장 예상치를 상회했다'" in request_text
    assert "'missed expectations' to '시장 예상치를 밑돌았다'" in request_text
    assert "same KEY count and order" in request_text