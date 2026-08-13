"""Tests for the Gemini structured-output summary adapter."""

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft
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
        if isinstance(self._response, Exception):
            raise self._response
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


@pytest.mark.parametrize(
    ("outcome", "code", "retryable"),
    [
        (httpx.ReadTimeout("slow"), "TIMEOUT", True),
        (httpx.ConnectError("offline"), "REQUEST_FAILED", True),
        (
            errors.ClientError(429, {"error": {"code": 429, "message": "quota"}}),
            "RATE_LIMITED",
            True,
        ),
        (
            errors.ClientError(400, {"error": {"code": 400, "message": "bad"}}),
            "REQUEST_FAILED",
            False,
        ),
        (
            errors.ServerError(500, {"error": {"code": 500, "message": "down"}}),
            "REQUEST_FAILED",
            True,
        ),
    ],
)
def test_gemini_summarizer_maps_provider_failures(
    outcome: Exception, code: str, retryable: bool
) -> None:
    article = make_article()

    with pytest.raises(DigestError) as raised:
        GeminiSummarizer(FakeClient(outcome), "test-gemini").summarize(article)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "summarize",
        code,
        retryable,
    )
    assert article.text not in raised.value.message
    assert str(article.canonical_url) not in raised.value.message


@pytest.mark.parametrize(
    "outcome",
    [
        errors.APIError(302, {"error": {"code": 302, "message": "unexpected response"}}),
        errors.UnknownApiResponseError("response could not be parsed"),
    ],
)
def test_gemini_summarizer_maps_unclassified_sdk_failures(outcome: Exception) -> None:
    article = make_article()

    with pytest.raises(DigestError) as raised:
        GeminiSummarizer(FakeClient(outcome), "test-gemini").summarize(article)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "summarize",
        "REQUEST_FAILED",
        False,
    )
    assert article.text not in raised.value.message
    assert str(article.canonical_url) not in raised.value.message


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            SimpleNamespace(parsed=None, candidates=[object()], prompt_feedback=None),
            "INVALID_RESPONSE",
        ),
        (
            SimpleNamespace(
                parsed={"summary": "incomplete"}, candidates=[object()], prompt_feedback=None
            ),
            "INVALID_RESPONSE",
        ),
        (
            SimpleNamespace(
                parsed=None,
                candidates=[],
                prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
            ),
            "REFUSAL",
        ),
    ],
)
def test_gemini_summarizer_maps_invalid_response_and_refusal(
    response: object, code: str
) -> None:
    article = make_article()

    with pytest.raises(DigestError) as raised:
        GeminiSummarizer(FakeClient(response), "test-gemini").summarize(article)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "summarize",
        code,
        False,
    )
    assert article.text not in raised.value.message
    assert str(article.canonical_url) not in raised.value.message
