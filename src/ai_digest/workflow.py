"""Deterministic orchestration for adding one public web article."""

from datetime import datetime
import hashlib
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ai_digest.classifiers.base import Classifier
from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft, SummaryRecord, VALID_CATEGORIES
from ai_digest.extractors.web import WebExtractor
from ai_digest.storage import SummaryRepository
from ai_digest.summarizers.base import Summarizer
from ai_digest.url_normalizer import normalize_public_url


_TAIPEI = ZoneInfo("Asia/Taipei")


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return slug or "article"


def _record_id(title: str, canonical_url: str, now: datetime) -> str:
    date = now.astimezone(_TAIPEI).strftime("%Y%m%d")
    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:8]
    return f"{date}-{_slug(title)}-{url_hash}"


def _assemble_payload(article: ExtractedArticle, draft: SummaryDraft, category: str, now: datetime) -> dict[str, object]:
    canonical_url = str(article.canonical_url)
    return {
        "schemaVersion": 1,
        "id": _record_id(article.title, canonical_url, now),
        "canonicalUrl": canonical_url,
        "sourceType": "web",
        "title": article.title,
        "author": article.author,
        "sourcePublishedAt": article.published_at,
        "createdAt": now,
        "updatedAt": now,
        "summary": draft.summary,
        "keyPoints": draft.key_points,
        "category": category,
        "tags": draft.tags,
        "editorial": draft.editorial,
        "status": "published",
    }


class AddArticleWorkflow:
    """Run normalization, extraction, summary, classification, and storage in order."""

    def __init__(
        self,
        extractor: WebExtractor,
        summarizer: Summarizer,
        classifier: Classifier,
        repository: SummaryRepository,
    ) -> None:
        self._extractor = extractor
        self._summarizer = summarizer
        self._classifier = classifier
        self._repository = repository

    def run(self, raw_url: str, now: datetime) -> SummaryRecord:
        """Create and save one fully validated published web summary record."""
        normalized_url = normalize_public_url(raw_url)
        self._reject_duplicate(normalized_url)
        article = self._extractor.extract(normalized_url)
        draft = self._summarizer.summarize(article)
        category = self._predict_category(article, draft)
        payload = _assemble_payload(article, draft, category, now)
        try:
            record = SummaryRecord.model_validate(payload)
        except ValidationError as error:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False) from error
        self._repository.save(record)
        return record

    def _reject_duplicate(self, canonical_url: str) -> None:
        if any(str(record.canonical_url) == canonical_url for record in self._repository.list()):
            raise DigestError("save", "DUPLICATE_URL", "A summary already exists for this URL", False)

    def _predict_category(self, article: ExtractedArticle, draft: SummaryDraft) -> str:
        text = "\n".join([article.title, draft.summary, *draft.key_points])
        category = self._classifier.predict(text)
        if category not in VALID_CATEGORIES:
            raise DigestError("classify", "INVALID_CATEGORY", "Predicted category is invalid", False)
        return category
