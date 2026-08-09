"""Interfaces for turning extracted articles into summary drafts."""

from typing import Protocol

from ai_digest.domain import ExtractedArticle, SummaryDraft


class Summarizer(Protocol):
    """Produce a validated summary draft from one extracted article."""

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        """Summarize an already extracted article."""

