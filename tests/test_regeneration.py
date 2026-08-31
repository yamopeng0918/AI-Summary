from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ai_digest.domain import (
    DigestError,
    ExtractedArticle,
    SummaryDraft,
    SummaryRecord,
    VALID_CATEGORIES,
)
from ai_digest.regeneration import RegenerateSummaryWorkflow


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 31, 10, 0, tzinfo=TAIPEI)
CATEGORY = next(iter(VALID_CATEGORIES))


def make_original() -> SummaryRecord:
    return SummaryRecord(
        schemaVersion=1,
        id="existing-summary",
        canonicalUrl="https://example.com/original",
        sourceType="web",
        title="Original title",
        author="Original author",
        sourcePublishedAt="2026-08-01T10:00:00+08:00",
        createdAt="2026-08-02T10:00:00+08:00",
        updatedAt="2026-08-03T10:00:00+08:00",
        summary="Original summary",
        keyPoints=["Original one", "Original two", "Original three"],
        category=CATEGORY,
        tags=["Original"],
        editorial="Original editorial",
        status="archived",
    )


def make_article() -> ExtractedArticle:
    return ExtractedArticle(
        canonicalUrl="https://example.com/resolved",
        sourceType="youtube",
        title="Refreshed title",
        author="Refreshed author",
        publishedAt="2026-08-30T09:00:00+08:00",
        text="Refreshed source text",
    )


def make_draft() -> SummaryDraft:
    return SummaryDraft(
        summary="Refreshed summary",
        keyPoints=["Refreshed one", "Refreshed two", "Refreshed three"],
        tags=["AI", "Digest"],
        editorial="Refreshed editorial",
    )


class FakeExtractor:
    def __init__(self, events: list[str], article: ExtractedArticle, error: Exception | None = None) -> None:
        self.events = events
        self.article = article
        self.error = error

    def extract(self, url: str) -> ExtractedArticle:
        self.events.append(f"extract:{url}")
        if self.error is not None:
            raise self.error
        return self.article


class FakeSummarizer:
    def __init__(self, events: list[str], draft: SummaryDraft, error: Exception | None = None) -> None:
        self.events = events
        self.draft = draft
        self.error = error

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        self.events.append("summarize")
        if self.error is not None:
            raise self.error
        return self.draft


class FakeClassifier:
    def __init__(self, events: list[str], category: str, error: Exception | None = None) -> None:
        self.events = events
        self.category = category
        self.error = error
        self.inputs: list[str] = []

    def predict(self, text: str) -> str:
        self.events.append("classify")
        self.inputs.append(text)
        if self.error is not None:
            raise self.error
        return self.category


class FakeRepository:
    def __init__(
        self,
        events: list[str],
        records: list[SummaryRecord],
        replace_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.records = {record.id: record for record in records}
        self.replace_error = replace_error

    def get(self, record_id: str) -> SummaryRecord:
        self.events.append(f"get:{record_id}")
        try:
            return self.records[record_id]
        except KeyError as error:
            raise DigestError("save", "RECORD_NOT_FOUND", "Summary record was not found", False) from error

    def list(self) -> list[SummaryRecord]:
        self.events.append("preflight")
        return list(self.records.values())

    def replace(self, record_id: str, updated_record: SummaryRecord) -> None:
        self.events.append(f"replace:{record_id}")
        if self.replace_error is not None:
            raise self.replace_error
        self.records[record_id] = updated_record


def make_workflow(
    events: list[str],
    *,
    original: SummaryRecord | None = None,
    article: ExtractedArticle | None = None,
    draft: SummaryDraft | None = None,
    category: str = CATEGORY,
    extra_records: list[SummaryRecord] | None = None,
    extractor_error: Exception | None = None,
    summarizer_error: Exception | None = None,
    classifier_error: Exception | None = None,
    replace_error: Exception | None = None,
    progress: list[str] | None = None,
) -> tuple[RegenerateSummaryWorkflow, FakeRepository, FakeClassifier, SummaryRecord]:
    saved_original = original or make_original()
    repository = FakeRepository(events, [saved_original, *(extra_records or [])], replace_error)
    classifier = FakeClassifier(events, category, classifier_error)
    workflow = RegenerateSummaryWorkflow(
        FakeExtractor(events, article or make_article(), extractor_error),
        FakeSummarizer(events, draft or make_draft(), summarizer_error),
        classifier,
        repository,
        on_progress=progress.append if progress is not None else None,
    )
    return workflow, repository, classifier, saved_original


def assert_original_unchanged(repository: FakeRepository, original: SummaryRecord) -> None:
    assert repository.records[original.id] == original


def test_regeneration_refreshes_source_fields_and_preserves_identity_and_archived_status() -> None:
    events: list[str] = []
    progress: list[str] = []
    article = make_article()
    draft = make_draft()
    workflow, repository, classifier, original = make_workflow(
        events, article=article, draft=draft, progress=progress
    )

    result = workflow.run(original.id, NOW)

    assert events == [
        "get:existing-summary",
        "extract:https://example.com/original",
        "preflight",
        "summarize",
        "classify",
        "replace:existing-summary",
    ]
    assert progress == ["input", "extract", "summarize", "classify", "validate", "save"]
    assert classifier.inputs == [
        "Refreshed title\n\nRefreshed summary\n\nRefreshed one\nRefreshed two\nRefreshed three"
    ]
    assert result.schema_version == 1
    assert result.id == original.id
    assert result.created_at == original.created_at
    assert result.status == original.status
    assert result.updated_at == NOW
    assert result.canonical_url == article.canonical_url
    assert result.source_type == article.source_type
    assert result.title == article.title
    assert result.author == article.author
    assert result.source_published_at == article.published_at
    assert result.summary == draft.summary
    assert result.key_points == draft.key_points
    assert result.category == CATEGORY
    assert result.tags == draft.tags
    assert result.editorial == draft.editorial
    assert repository.records[original.id] == result


def test_regeneration_leaves_repository_unchanged_when_target_is_missing() -> None:
    events: list[str] = []
    repository = FakeRepository(events, [])
    workflow = RegenerateSummaryWorkflow(
        FakeExtractor(events, make_article()),
        FakeSummarizer(events, make_draft()),
        FakeClassifier(events, CATEGORY),
        repository,
    )

    with pytest.raises(DigestError) as raised:
        workflow.run("missing", NOW)

    assert (raised.value.stage, raised.value.code) == ("save", "RECORD_NOT_FOUND")
    assert events == ["get:missing"]
    assert repository.records == {}


def test_regeneration_leaves_original_unchanged_when_extraction_fails() -> None:
    events: list[str] = []
    progress: list[str] = []
    failure = DigestError("extract", "FAILED", "safe", False)
    workflow, repository, _, original = make_workflow(
        events, extractor_error=failure, progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert raised.value is failure
    assert events == ["get:existing-summary", "extract:https://example.com/original"]
    assert progress == ["input", "extract"]
    assert_original_unchanged(repository, original)


def test_regeneration_rejects_resolved_canonical_collision_before_summarizing() -> None:
    events: list[str] = []
    progress: list[str] = []
    conflicting = make_original().model_copy(
        update={"id": "conflicting-summary", "canonical_url": "https://example.com/resolved"}
    )
    workflow, repository, classifier, original = make_workflow(
        events, extra_records=[conflicting], progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "input",
        "DUPLICATE_URL",
        False,
    )
    assert events == [
        "get:existing-summary",
        "extract:https://example.com/original",
        "preflight",
    ]
    assert progress == ["input", "extract"]
    assert classifier.inputs == []
    assert "summarize" not in events
    assert_original_unchanged(repository, original)


def test_regeneration_leaves_original_unchanged_when_summarization_fails() -> None:
    events: list[str] = []
    progress: list[str] = []
    failure = DigestError("summarize", "FAILED", "safe", False)
    workflow, repository, _, original = make_workflow(
        events, summarizer_error=failure, progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert raised.value is failure
    assert progress == ["input", "extract", "summarize"]
    assert_original_unchanged(repository, original)


def test_regeneration_rejects_invalid_classifier_category_without_replacing_original() -> None:
    events: list[str] = []
    progress: list[str] = []
    workflow, repository, _, original = make_workflow(
        events, category="not-a-category", progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "classify",
        "INVALID_CATEGORY",
        False,
    )
    assert progress == ["input", "extract", "summarize", "classify"]
    assert "replace:existing-summary" not in events
    assert_original_unchanged(repository, original)


def test_regeneration_leaves_original_unchanged_when_classification_fails() -> None:
    events: list[str] = []
    progress: list[str] = []
    failure = DigestError("classify", "FAILED", "safe", False)
    workflow, repository, _, original = make_workflow(
        events, classifier_error=failure, progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert raised.value is failure
    assert progress == ["input", "extract", "summarize", "classify"]
    assert_original_unchanged(repository, original)


def test_regeneration_maps_record_validation_error_and_leaves_original_unchanged() -> None:
    events: list[str] = []
    progress: list[str] = []
    invalid_article = make_article()
    invalid_article.title = " "
    workflow, repository, _, original = make_workflow(
        events, article=invalid_article, progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "INVALID_RECORD",
        False,
    )
    assert progress == ["input", "extract", "summarize", "classify", "validate"]
    assert "replace:existing-summary" not in events
    assert_original_unchanged(repository, original)


def test_regeneration_leaves_original_unchanged_when_repository_replace_fails() -> None:
    events: list[str] = []
    progress: list[str] = []
    failure = DigestError("save", "WRITE_FAILED", "safe", True)
    workflow, repository, _, original = make_workflow(
        events, replace_error=failure, progress=progress
    )

    with pytest.raises(DigestError) as raised:
        workflow.run(original.id, NOW)

    assert raised.value is failure
    assert progress == ["input", "extract", "summarize", "classify", "validate", "save"]
    assert events[-1] == "replace:existing-summary"
    assert_original_unchanged(repository, original)
