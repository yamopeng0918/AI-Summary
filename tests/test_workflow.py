from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ai_digest.classifiers.base import Classifier
from ai_digest.classifiers.fixed import FixedClassifier
from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft, SummaryRecord, VALID_CATEGORIES
from ai_digest.summarizers.base import Summarizer
from ai_digest.workflow import AddArticleWorkflow


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 9, 14, 0, tzinfo=TAIPEI)
CATEGORY = next(iter(VALID_CATEGORIES))


def make_article(title: str = "可信賴的 AI 摘要", source_type: str = "web") -> ExtractedArticle:
    return ExtractedArticle(
        canonicalUrl="https://example.com/article",
        sourceType=source_type,
        title=title,
        author="作者",
        publishedAt="2026-08-08T10:00:00+08:00",
        text="公開文章內容。",
    )


def make_draft() -> SummaryDraft:
    return SummaryDraft(
        summary="這是一段繁體中文摘要。",
        keyPoints=["第一個重點", "第二個重點", "第三個重點"],
        tags=[" AI ", "ai", "資料科學"],
        editorial="編輯觀點。",
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
    def __init__(self, events: list[str], existing: list[SummaryRecord] | None = None) -> None:
        self.events = events
        self.records = list(existing or [])
        self.saved: list[SummaryRecord] = []

    def list(self) -> list[SummaryRecord]:
        self.events.append("preflight")
        return self.records

    def save(self, record: SummaryRecord) -> None:
        self.events.append("save")
        self.saved.append(record)


def make_workflow(
    events: list[str],
    *,
    article: ExtractedArticle | None = None,
    category: str = CATEGORY,
    existing: list[SummaryRecord] | None = None,
    summarizer_error: Exception | None = None,
    classifier_error: Exception | None = None,
    progress: list[str] | None = None,
) -> tuple[AddArticleWorkflow, FakeRepository, FakeClassifier]:
    extractor = FakeExtractor(events, article or make_article())
    summarizer: Summarizer = FakeSummarizer(events, make_draft(), summarizer_error)
    classifier: Classifier = FakeClassifier(events, category, classifier_error)
    repository = FakeRepository(events, existing)
    return (
        AddArticleWorkflow(
            extractor,
            summarizer,
            classifier,
            repository,
            on_progress=progress.append if progress is not None else None,
        ),
        repository,
        classifier,
    )


def test_fixed_classifier_validates_category_and_implements_classifier_protocol() -> None:
    classifier: Classifier = FixedClassifier(CATEGORY)

    assert classifier.predict("anything") == CATEGORY
    with pytest.raises(DigestError) as raised:
        FixedClassifier("not-a-category")
    assert (raised.value.stage, raised.value.code) == ("classify", "INVALID_CATEGORY")


def test_workflow_runs_normalize_preflight_extract_summarize_classify_and_save_in_order(monkeypatch) -> None:
    events: list[str] = []
    progress: list[str] = []
    workflow, repository, classifier = make_workflow(events, progress=progress)

    def normalize(raw_url: str) -> str:
        events.append(f"normalize:{raw_url}")
        return "https://example.com/article"

    monkeypatch.setattr("ai_digest.workflow.canonicalize_source_url", normalize)
    result = workflow.run("HTTPS://EXAMPLE.COM/article?utm_source=test", NOW)

    assert events == [
        "normalize:HTTPS://EXAMPLE.COM/article?utm_source=test",
        "preflight",
        "extract:https://example.com/article",
        "summarize",
        "classify",
        "save",
    ]
    assert repository.saved == [result]
    assert result.status == "published"
    assert result.source_type == "web"
    assert result.title == "可信賴的 AI 摘要"
    assert result.author == "作者"
    assert result.source_published_at == datetime(2026, 8, 8, 10, 0, tzinfo=TAIPEI)
    assert result.created_at == NOW
    assert result.updated_at == NOW
    assert result.tags == ["AI", "資料科學"]
    assert classifier.inputs == ["可信賴的 AI 摘要\n\n這是一段繁體中文摘要。\n\n第一個重點\n第二個重點\n第三個重點"]


    assert progress == ["input", "extract", "summarize", "classify", "validate", "save"]


def test_workflow_generates_readable_deterministic_unicode_title_slug() -> None:
    events: list[str] = []
    workflow, _, _ = make_workflow(events, article=make_article("台灣 AI：新世代摘要！"))

    result = workflow.run("https://example.com/article", NOW)

    assert result.id.startswith("20260809-台灣-ai-新世代摘要-")
    assert result.id == workflow.run("https://example.com/article", NOW).id
    assert len(result.id.rsplit("-", 1)[1]) == 8


def test_workflow_rejects_existing_canonical_url_before_any_remote_stage(monkeypatch) -> None:
    events: list[str] = []
    existing = SummaryRecord(
        schemaVersion=1,
        id="existing",
        canonicalUrl="https://example.com/article",
        sourceType="web",
        title="Existing",
        author=None,
        sourcePublishedAt=None,
        createdAt=NOW,
        updatedAt=NOW,
        summary="Summary",
        keyPoints=["One", "Two", "Three"],
        category=CATEGORY,
        tags=["AI"],
        editorial="Editorial",
        status="published",
    )
    workflow, repository, classifier = make_workflow(events, existing=[existing])
    monkeypatch.setattr("ai_digest.workflow.canonicalize_source_url", lambda raw_url: events.append("normalize") or "https://example.com/article")

    with pytest.raises(DigestError) as raised:
        workflow.run("https://example.com/article", NOW)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "input",
        "DUPLICATE_URL",
        False,
    )
    assert events == ["normalize", "preflight"]
    assert classifier.inputs == []
    assert repository.saved == []


def test_workflow_rejects_bluesky_did_alias_after_extraction_before_summary() -> None:
    events: list[str] = []
    existing = SummaryRecord(
        schemaVersion=1,
        id="existing-social-post",
        canonicalUrl="https://bsky.app/profile/did:plc:alice/post/3social",
        sourceType="social",
        title="Existing Bluesky post",
        author=None,
        sourcePublishedAt=None,
        createdAt=NOW,
        updatedAt=NOW,
        summary="Summary",
        keyPoints=["One", "Two", "Three"],
        category=CATEGORY,
        tags=["Bluesky"],
        editorial="Editorial",
        status="published",
    )
    article = make_article(source_type="social").model_copy(
        update={"canonical_url": "https://bsky.app/profile/did:plc:alice/post/3social"}
    )
    workflow, repository, classifier = make_workflow(events, article=article, existing=[existing])

    with pytest.raises(DigestError) as raised:
        workflow.run("https://bsky.app/profile/alice.example/post/3social", NOW)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "input",
        "DUPLICATE_URL",
        False,
    )
    assert events == [
        "preflight",
        "extract:https://bsky.app/profile/alice.example/post/3social",
        "preflight",
    ]
    assert classifier.inputs == []
    assert repository.saved == []


@pytest.mark.parametrize(
    ("summarizer_error", "classifier_error", "category", "stage"),
    [
        (DigestError("summarize", "FAILED", "safe", False), None, CATEGORY, "summarize"),
        (None, DigestError("classify", "FAILED", "safe", False), CATEGORY, "classify"),
        (None, None, "not-a-category", "classify"),
    ],
)
def test_workflow_leaves_repository_empty_when_an_upstream_stage_fails(
    summarizer_error: Exception | None,
    classifier_error: Exception | None,
    category: str,
    stage: str,
) -> None:
    events: list[str] = []
    workflow, repository, _ = make_workflow(
        events,
        summarizer_error=summarizer_error,
        classifier_error=classifier_error,
        category=category,
    )

    with pytest.raises(DigestError) as raised:
        workflow.run("https://example.com/article", NOW)

    assert raised.value.stage == stage
    assert repository.saved == []
    assert "save" not in events


def test_workflow_progress_stops_after_early_failure() -> None:
    events: list[str] = []
    progress: list[str] = []
    workflow, repository, _ = make_workflow(
        events,
        summarizer_error=DigestError("summarize", "FAILED", "safe", False),
        progress=progress,
    )

    with pytest.raises(DigestError):
        workflow.run("https://example.com/article", NOW)

    assert progress == ["input", "extract", "summarize"]
    assert repository.saved == []


def test_workflow_persists_youtube_source_type_and_canonical_url() -> None:
    events: list[str] = []
    article = make_article(source_type="youtube").model_copy(
        update={"canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    workflow, repository, _ = make_workflow(events, article=article)

    result = workflow.run("https://youtu.be/dQw4w9WgXcQ?t=10", NOW)

    assert str(result.canonical_url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert result.source_type == "youtube"
    assert repository.saved == [result]


def test_workflow_rejects_equivalent_youtube_url_before_extraction() -> None:
    events: list[str] = []
    existing = SummaryRecord(
        schemaVersion=1,
        id="existing-youtube",
        canonicalUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        sourceType="youtube",
        title="Existing video",
        author=None,
        sourcePublishedAt=None,
        createdAt=NOW,
        updatedAt=NOW,
        summary="Summary",
        keyPoints=["One", "Two", "Three"],
        category=CATEGORY,
        tags=["YouTube"],
        editorial="Editorial",
        status="published",
    )
    workflow, repository, classifier = make_workflow(events, existing=[existing])

    with pytest.raises(DigestError) as raised:
        workflow.run("https://youtu.be/dQw4w9WgXcQ?t=10", NOW)

    assert raised.value.code == "DUPLICATE_URL"
    assert events == ["preflight"]
    assert classifier.inputs == []
    assert repository.saved == []
