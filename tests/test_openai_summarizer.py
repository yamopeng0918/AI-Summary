from types import SimpleNamespace

import pytest
from httpx import Request
from openai import APITimeoutError

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft
from ai_digest.summarizers.openai import OpenAISummarizer


def article() -> ExtractedArticle:
    return ExtractedArticle(
        canonical_url="https://example.com/ai",
        title="AI article",
        author="Author",
        published_at=None,
        text="Source text that must not appear in public error messages.",
    )


def draft() -> SummaryDraft:
    return SummaryDraft(
        summary="繁體中文摘要",
        keyPoints=["重點一", "重點二", "重點三"],
        tags=["AI"],
        editorial="編輯觀點",
    )


class FakeCompletions:
    def __init__(self, response: object | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def client_for(response: object | Exception) -> tuple[object, FakeCompletions]:
    completions = FakeCompletions(response)
    client = SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return client, completions


def parsed_response(value: SummaryDraft | None, refusal: str | None = None) -> object:
    message = SimpleNamespace(parsed=value, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_structured_summary_uses_constrained_traditional_chinese_instruction() -> None:
    client, completions = client_for(parsed_response(draft()))

    result = OpenAISummarizer(client, "gpt-test").summarize(article())

    assert result == draft()
    call = completions.calls[0]
    assert call["model"] == "gpt-test"
    assert call["response_format"] is SummaryDraft
    instruction = call["messages"][0]["content"]
    assert "繁體中文" in instruction
    assert "3 至 5" in instruction
    assert "1 至 5" in instruction
    assert "不得加入來源未支持" in instruction


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (parsed_response(None, refusal="no"), "REFUSED"),
        (parsed_response(None), "MISSING_CONTENT"),
        (parsed_response({"summary": "not a draft"}), "INVALID_RESPONSE"),
    ],
)
def test_invalid_structured_responses_become_safe_summary_errors(
    response: object, code: str
) -> None:
    client, _ = client_for(response)

    with pytest.raises(DigestError) as raised:
        OpenAISummarizer(client, "gpt-test").summarize(article())

    assert raised.value.stage == "summarize"
    assert raised.value.code == code
    assert "Source text" not in raised.value.message
    assert "AI article" not in raised.value.message


def test_timeout_becomes_retryable_safe_summary_error() -> None:
    client, _ = client_for(APITimeoutError(Request("POST", "https://api.example.test")))

    with pytest.raises(DigestError) as raised:
        OpenAISummarizer(client, "gpt-test").summarize(article())

    assert raised.value.stage == "summarize"
    assert raised.value.code == "TIMEOUT"
    assert raised.value.retryable is True
    assert "api.example.test" not in raised.value.message
