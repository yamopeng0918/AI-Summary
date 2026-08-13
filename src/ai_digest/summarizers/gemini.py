"""Gemini structured-output adapter for article summaries."""

from typing import Any

import httpx
from google.genai import errors
from google.genai import types
from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft
from ai_digest.summarizers.openai import _SYSTEM_INSTRUCTION


class GeminiSummarizer:
    """Create validated drafts through the Gemini structured-output API."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        """Return a structured summary or a safe summarization error."""
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=f"標題：{article.title}\n\n內容：{article.text}",
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=SummaryDraft,
                ),
            )
        except httpx.TimeoutException as error:
            raise DigestError("summarize", "TIMEOUT", "Summary request timed out", True) from error
        except httpx.TransportError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", True) from error
        except errors.ClientError as error:
            if error.code == 429:
                raise DigestError(
                    "summarize", "RATE_LIMITED", "Summary service is rate limited", True
                ) from error
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", False) from error
        except errors.ServerError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", True) from error
        except errors.APIError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", False) from error
        except errors.UnknownApiResponseError as error:
            raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", False) from error

        try:
            if not response.candidates and response.prompt_feedback.block_reason:
                raise DigestError("summarize", "REFUSAL", "Summary request was refused", False)
            if response.parsed is None:
                raise DigestError("summarize", "INVALID_RESPONSE", "Summary response is invalid", False)
            return SummaryDraft.model_validate(response.parsed)
        except DigestError:
            raise
        except (AttributeError, TypeError, ValidationError) as error:
            raise DigestError(
                "summarize", "INVALID_RESPONSE", "Summary response is invalid", False
            ) from error
