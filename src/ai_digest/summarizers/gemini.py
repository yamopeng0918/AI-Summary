"""Gemini structured-output adapter for article summaries."""

from typing import Any

from google.genai import types

from ai_digest.domain import ExtractedArticle, SummaryDraft
from ai_digest.summarizers.openai import _SYSTEM_INSTRUCTION


class GeminiSummarizer:
    """Create validated drafts through the Gemini structured-output API."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        """Return a validated structured summary draft."""
        response = self._client.models.generate_content(
            model=self._model,
            contents=f"標題：{article.title}\n\n內容：{article.text}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=SummaryDraft,
            ),
        )
        return SummaryDraft.model_validate(response.parsed)
