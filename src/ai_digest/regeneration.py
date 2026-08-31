"""Orchestration for regenerating an existing summary from its source."""

from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from ai_digest.classifiers.base import Classifier
from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES
from ai_digest.extractors.base import Extractor
from ai_digest.storage import SummaryRepository
from ai_digest.summarizers.base import Summarizer


class RegenerateSummaryWorkflow:
    """Refresh source-derived fields while preserving an existing record's identity."""

    def __init__(
        self,
        extractor: Extractor,
        summarizer: Summarizer,
        classifier: Classifier,
        repository: SummaryRepository,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._extractor = extractor
        self._summarizer = summarizer
        self._classifier = classifier
        self._repository = repository
        self._on_progress = on_progress or (lambda stage: None)

    def run(self, record_id: str, now: datetime) -> SummaryRecord:
        """Regenerate one stored summary after source and collision preflight checks."""
        self._on_progress("input")
        original = self._repository.get(record_id)

        self._on_progress("extract")
        article = self._extractor.extract(str(original.canonical_url))
        resolved_url = str(article.canonical_url)
        if any(
            existing.id != record_id and str(existing.canonical_url) == resolved_url
            for existing in self._repository.list()
        ):
            raise DigestError(
                "input", "DUPLICATE_URL", "A summary already exists for this URL", False
            )

        self._on_progress("summarize")
        draft = self._summarizer.summarize(article)
        classifier_text = "\n\n".join(
            [article.title, draft.summary, "\n".join(draft.key_points)]
        )
        self._on_progress("classify")
        category = self._classifier.predict(classifier_text)
        if category not in VALID_CATEGORIES:
            raise DigestError("classify", "INVALID_CATEGORY", "Category is not configured", False)

        self._on_progress("validate")
        try:
            updated = SummaryRecord(
                schemaVersion=1,
                id=original.id,
                canonicalUrl=article.canonical_url,
                sourceType=article.source_type,
                title=article.title,
                author=article.author,
                sourcePublishedAt=article.published_at,
                createdAt=original.created_at,
                updatedAt=now,
                summary=draft.summary,
                keyPoints=draft.key_points,
                category=category,
                tags=draft.tags,
                editorial=draft.editorial,
                status=original.status,
            )
        except ValidationError as error:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False) from error

        self._on_progress("save")
        self._repository.replace(record_id, updated)
        return updated
