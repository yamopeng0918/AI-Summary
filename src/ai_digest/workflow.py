"""Orchestration for adding one web article summary."""

from collections.abc import Callable
from datetime import datetime
import hashlib
import re
import unicodedata
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ai_digest.classifiers.base import Classifier
from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES
from ai_digest.extractors.base import Extractor
from ai_digest.storage import SummaryRepository
from ai_digest.summarizers.base import Summarizer
from ai_digest.source_urls import canonicalize_source_url


_TAIPEI = ZoneInfo("Asia/Taipei")


def _title_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-_")
    return slug or "article"


def _record_id(title: str, canonical_url: str, now: datetime) -> str:
    date = now.astimezone(_TAIPEI).strftime("%Y%m%d")
    suffix = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:8]
    return f"{date}-{_title_slug(title)}-{suffix}"


def _has_canonical_url(repository: SummaryRepository, canonical_url: str) -> bool:
    return any(str(record.canonical_url) == canonical_url for record in repository.list())


class AddArticleWorkflow:
    """Coordinate preflight, extraction, summarization, classification, and saving."""

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

    def run(self, raw_url: str, now: datetime) -> SummaryRecord:
        """Create and atomically save a published summary record."""
        self._on_progress("input")
        canonical_url = canonicalize_source_url(raw_url)
        if _has_canonical_url(self._repository, canonical_url):
            raise DigestError("input", "DUPLICATE_URL", "A summary already exists for this URL", False)

        self._on_progress("extract")
        article = self._extractor.extract(canonical_url)
        resolved_url = str(article.canonical_url)
        if resolved_url != canonical_url and _has_canonical_url(self._repository, resolved_url):
            raise DigestError("input", "DUPLICATE_URL", "A summary already exists for this URL", False)
        self._on_progress("summarize")
        draft = self._summarizer.summarize(article)
        classifier_text = "\n\n".join([article.title, draft.summary, "\n".join(draft.key_points)])
        self._on_progress("classify")
        category = self._classifier.predict(classifier_text)
        if category not in VALID_CATEGORIES:
            raise DigestError("classify", "INVALID_CATEGORY", "Category is not configured", False)

        self._on_progress("validate")
        try:
            record = SummaryRecord(
                schemaVersion=1,
                id=_record_id(article.title, str(article.canonical_url), now),
                canonicalUrl=article.canonical_url,
                sourceType=article.source_type,
                title=article.title,
                author=article.author,
                sourcePublishedAt=article.published_at,
                createdAt=now,
                updatedAt=now,
                summary=draft.summary,
                keyPoints=draft.key_points,
                category=category,
                tags=draft.tags,
                editorial=draft.editorial,
                status="published",
            )
        except ValidationError as error:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False) from error

        self._on_progress("save")
        self._repository.save(record)
        return record
