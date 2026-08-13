"""Tests for the Gemini structured-output summary adapter."""

from types import SimpleNamespace

from ai_digest.domain import ExtractedArticle, SummaryDraft
from ai_digest.summarizers.base import Summarizer
from ai_digest.summarizers.gemini import GeminiSummarizer


def make_article() -> ExtractedArticle:
    return ExtractedArticle(
        canonicalUrl="https://example.com/article",
        title="測試 AI 文章",
        author="測試作者",
        publishedAt="2026-08-09T10:00:00+08:00",
        text="這是一篇用於驗證 Gemini 摘要器的文章內容。",
    )


def make_draft() -> SummaryDraft:
    return SummaryDraft(
        summary="這是一篇經結構化輸出驗證的摘要。",
        keyPoints=["重點一", "重點二", "重點三"],
        tags=["AI"],
        editorial="這是 AI 編輯觀點。",
    )


class FakeModels:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response: object) -> None:
        self.models = FakeModels(response)


def test_gemini_summarizer_uses_structured_output_and_returns_validated_draft() -> None:
    client = FakeClient(
        SimpleNamespace(parsed=make_draft(), candidates=[object()], prompt_feedback=None)
    )
    summarizer: Summarizer = GeminiSummarizer(client, "test-gemini")

    result = summarizer.summarize(make_article())

    assert result == make_draft()
    call = client.models.calls[0]
    assert call["model"] == "test-gemini"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is SummaryDraft
    assert make_article().title in call["contents"]
