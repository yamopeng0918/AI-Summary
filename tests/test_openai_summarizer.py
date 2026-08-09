from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIResponseValidationError, APITimeoutError, RateLimitError

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft
from ai_digest.summarizers.base import Summarizer
from ai_digest.summarizers.openai import OpenAISummarizer


def make_article() -> ExtractedArticle:
    return ExtractedArticle(
        canonicalUrl="https://example.com/article",
        title="可信賴的 AI 摘要",
        author="作者",
        publishedAt="2026-08-09T10:00:00+08:00",
        text="可公開讀取的文章內容。",
    )


def make_draft() -> SummaryDraft:
    return SummaryDraft(
        summary="這是一段繁體中文摘要。",
        keyPoints=["第一個重點", "第二個重點", "第三個重點"],
        tags=["AI"],
        editorial="編輯觀點。",
    )


class FakeCompletions:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome: object) -> None:
        self.completions = FakeCompletions(outcome)
        self.beta = SimpleNamespace(chat=SimpleNamespace(completions=self.completions))


def parsed_response(parsed: object | None, refusal: str | None = None) -> object:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=refusal))])


def response_validation_error() -> APIResponseValidationError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(200, request=request)
    return APIResponseValidationError(response, {"invalid": "response"})


def rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_openai_summarizer_satisfies_summarizer_protocol_and_uses_structured_draft() -> None:
    client = FakeClient(parsed_response(make_draft()))
    summarizer: Summarizer = OpenAISummarizer(client=client, model="test-model")

    result = summarizer.summarize(make_article())

    assert result == make_draft()
    call = client.completions.calls == [client.completions.calls[0]] and client.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["response_format"] is SummaryDraft
    system_instruction = call["messages"][0]["content"]
    assert "繁體中文" in system_instruction
    assert "3 至 5" in system_instruction
    assert "1 至 5" in system_instruction
    assert "不得加入來源未支持的事實" in system_instruction


@pytest.mark.parametrize(
    ("outcome", "code", "retryable"),
    [
        (parsed_response(None, refusal="cannot comply"), "REFUSAL", False),
        (parsed_response(None), "INVALID_RESPONSE", False),
        (APITimeoutError(httpx.Request("POST", "https://api.openai.com")), "TIMEOUT", True),
        (response_validation_error(), "INVALID_RESPONSE", False),
        (rate_limit_error(), "RATE_LIMITED", True),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.com"),
                message="connection failed",
            ),
            "REQUEST_FAILED",
            True,
        ),
        (parsed_response({"summary": "not a SummaryDraft"}), "INVALID_RESPONSE", False),
    ],
)
def test_openai_summarizer_maps_known_failures_to_safe_digest_errors(
    outcome: object, code: str, retryable: bool
) -> None:
    article = make_article()
    summarizer = OpenAISummarizer(client=FakeClient(outcome), model="test-model")

    with pytest.raises(DigestError) as raised:
        summarizer.summarize(article)

    error = raised.value
    assert (error.stage, error.code, error.retryable) == ("summarize", code, retryable)
    assert article.text not in error.message
    assert str(article.canonical_url) not in error.message

