"""OpenAI structured-output adapter for article summaries."""

from typing import Any

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft


_SYSTEM_INSTRUCTION = """你是 AI Digest 的摘要編輯。請以繁體中文產生摘要、3 至 5 個重點、1 至 5 個標籤與編輯觀點。不得加入來源未支持的事實。"""


class OpenAISummarizer:
    """Create validated drafts through the OpenAI structured-output API."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        """Return a structured summary or a safe summarization error."""
        try:
            response = self._client.beta.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_INSTRUCTION},
                    {
                        "role": "user",
                        "content": f"標題：{article.title}\n\n內容：{article.text}",
                    },
                ],
                response_format=SummaryDraft,
            )
        except APITimeoutError as error:
            raise DigestError("summarize", "TIMEOUT", "Summary request timed out", True) from error
        except RateLimitError as error:
            raise DigestError("summarize", "RATE_LIMITED", "Summary service is rate limited", True) from error
        except APIResponseValidationError as error:
            raise DigestError("summarize", "INVALID_RESPONSE", "Summary response is invalid", False) from error
        except APIConnectionError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", True) from error
        except APIStatusError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", error.status_code >= 500) from error

        try:
            message = response.choices[0].message
            if message.refusal:
                raise DigestError("summarize", "REFUSAL", "Summary request was refused", False)
            if message.parsed is None:
                raise DigestError("summarize", "INVALID_RESPONSE", "Summary response is invalid", False)
            return SummaryDraft.model_validate(message.parsed)
        except DigestError:
            raise
        except (AttributeError, IndexError, TypeError, ValidationError) as error:
            raise DigestError("summarize", "INVALID_RESPONSE", "Summary response is invalid", False) from error
