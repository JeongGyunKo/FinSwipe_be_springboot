from __future__ import annotations

from app.services.summarizer.summarizer import _cached_summary_completion
from app.services.summarizer import summarize_to_three_lines
from app.services.summarizer.summarizer import _prepare_summary_input


def test_summarizer_uses_Gemini_when_configured(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "매출이 시장 기대를 웃돌았습니다.\n"
                                "회사는 수요 강세와 마진 개선을 강조했습니다.\n"
                                "투자자들은 향후 가이던스 유지 여부를 주목하고 있습니다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=(
            "The company reported quarterly revenue of $12.4 billion, up 8% from a year earlier. "
            "Management said cloud demand remained strong and raised its full-year outlook. "
            "Operating margin narrowed as the company increased AI infrastructure spending."
        ),
    )

    assert summary == [
        "매출이 시장 기대를 웃돌았습니다.",
        "회사는 수요 강세와 마진 개선을 강조했습니다.",
        "투자자들은 향후 가이던스 유지 여부를 주목하고 있습니다.",
    ]


def test_summarizer_prompt_defines_three_line_roles(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
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
                            "parts": [{"text": (
                                "매출은 전년 대비 12% 증가했다.\n"
                                "주가는 실적 발표 이후 상승했다.\n"
                                "회사는 연간 가이던스를 상향했다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        captured.update(kwargs.get("json", {}))
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text="Revenue rose 12%. Shares rose after earnings. Guidance was raised.",
    )

    request_text = str(captured)
    assert "Line 1 must summarize the core event or financial result" in request_text
    assert "Line 2 must summarize the business, market, analyst, or stock-price impact" in request_text
    assert "Line 3 must summarize guidance, risk, outlook, cash flow, shareholder return" in request_text
    assert "silently verify: exactly 3 lines" in request_text


def test_summarizer_splits_single_line_Gemini_output_into_three_sentences(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "매출은 전년 대비 12% 증가했다. "
                                "영업 마진은 개선됐다. "
                                "회사는 연간 가이던스를 상향 조정했다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=(
            "Revenue rose 12% year over year. "
            "Operating margin improved. "
            "Management raised full-year guidance."
        ),
    )

    assert summary == [
        "매출은 전년 대비 12% 증가했다.",
        "영업 마진은 개선됐다.",
        "회사는 연간 가이던스를 상향 조정했다.",
    ]


def test_summarizer_accepts_json_array_output(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                '{"summary":["매출은 전년 대비 12% 증가했다.","영업 마진은 개선됐다.","회사는 연간 가이던스를 상향 조정했다."]}'
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=(
            "Revenue rose 12% year over year. "
            "Operating margin improved. "
            "Management raised full-year guidance."
        ),
    )

    assert summary == [
        "매출은 전년 대비 12% 증가했다.",
        "영업 마진은 개선됐다.",
        "회사는 연간 가이던스를 상향 조정했다.",
    ]


def test_summarizer_accepts_code_fenced_json_output(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "```json\n"
                                '{"summary_1":"매출은 전년 대비 12% 증가했다.","summary_2":"영업 마진은 개선됐다.","summary_3":"회사는 연간 가이던스를 상향 조정했다."}\n'
                                "```"
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=(
            "Revenue rose 12% year over year. "
            "Operating margin improved. "
            "Management raised full-year guidance."
        ),
    )

    assert summary == [
        "매출은 전년 대비 12% 증가했다.",
        "영업 마진은 개선됐다.",
        "회사는 연간 가이던스를 상향 조정했다.",
    ]


def test_summarizer_accepts_Gemini_output_even_when_numbers_differ(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash-lite")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": (
                                "매출은 전년 대비 12% 증가했다.\n"
                                "영업 마진은 개선됐다.\n"
                                "매출은 강한 수요로 전년 대비 15% 증가했다."
                            )}]
                        }
                    }
                ]
            }

    def _fake_post(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=(
            "Revenue rose 12% year over year. "
            "Operating margin improved. "
            "Management raised full-year guidance."
        ),
    )

    assert summary == [
        "매출은 전년 대비 12% 증가했다.",
        "영업 마진은 개선됐다.",
        "매출은 강한 수요로 전년 대비 15% 증가했다.",
    ]


def test_summarizer_skips_Gemini_for_oversized_articles(monkeypatch) -> None:
    _cached_summary_completion.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setenv("GEMINI_SUMMARY_HARD_CHAR_LIMIT", "100")

    def _unexpected_post(*args, **kwargs):
        raise AssertionError("Gemini should not be called for oversized articles")

    monkeypatch.setattr("app.services.gemini.client.requests.post", _unexpected_post)

    article_text = (
        "Revenue rose 12% year over year. "
        "Operating margin improved. "
        "Management raised full-year guidance. "
        "Demand remained strong across cloud and enterprise customers. "
        "Shares rose after the earnings release."
    )

    summary = summarize_to_three_lines(
        title="Company raises outlook after quarterly results",
        article_text=article_text,
    )

    assert summary == ["", "", ""]


def test_prepare_summary_input_samples_front_middle_and_back_sections(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_SUMMARY_SOFT_CHAR_LIMIT", "220")
    article_text = " ".join(
        [
            "Sentence one discusses the opening market reaction in detail.",
            "Sentence two covers early analyst commentary around margins.",
            "Sentence three explains how revenue trends compare with estimates.",
            "Sentence four shifts to management guidance and cloud demand.",
            "Sentence five highlights investor concern about costs and capex.",
            "Sentence six covers the market close and the stock response afterward.",
        ]
    )

    prepared = _prepare_summary_input(article_text)

    assert "Sentence one discusses the opening market reaction in detail." in prepared
    assert "Sentence four shifts to management guidance and cloud demand." in prepared
    assert "Sentence six covers the market close and the stock response afterward." in prepared