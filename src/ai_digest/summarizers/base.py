"""Protocol boundary for article summarization."""

from typing import Protocol

from ai_digest.domain import ExtractedArticle, SummaryDraft


class Summarizer(Protocol):
    """Generate a structured summary draft for an extracted article."""

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        """Return a validated draft without saving or classifying it."""
