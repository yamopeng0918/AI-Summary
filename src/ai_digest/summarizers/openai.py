"""OpenAI structured-output adapter for summary drafts."""

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft


_SYSTEM_INSTRUCTION = """你是內容編輯。請以繁體中文輸出摘要、3 至 5 個重點、1 至 5 個標籤及編輯觀點。
所有內容必須忠於提供的來源；不得加入來源未支持的事實。"""


class OpenAISummarizer:
    """Generate `SummaryDraft` instances via OpenAI structured output."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        """Return a safe, validated structured summary for one article."""
        try:
            completion = self._client.beta.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_INSTRUCTION},
                    {
                        "role": "user",
                        "content": f"標題：{article.title}\n來源：{article.text}",
                    },
                ],
                response_format=SummaryDraft,
            )
            message = completion.choices[0].message
            if message.refusal:
                raise DigestError("summarize", "REFUSED", "Summary request was refused", False)
            if message.parsed is None:
                raise DigestError(
                    "summarize", "MISSING_CONTENT", "Summary response was empty", True
                )
            return SummaryDraft.model_validate(message.parsed)
        except DigestError:
            raise
        except APITimeoutError as error:
            raise DigestError("summarize", "TIMEOUT", "Summary request timed out", True) from error
        except RateLimitError as error:
            raise DigestError("summarize", "RATE_LIMITED", "Summary service is rate limited", True) from error
        except APIConnectionError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", True) from error
        except APIStatusError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary service request failed", True) from error
        except (AttributeError, IndexError, KeyError, TypeError, ValidationError) as error:
            raise DigestError(
                "summarize", "INVALID_RESPONSE", "Summary response was invalid", False
            ) from error
