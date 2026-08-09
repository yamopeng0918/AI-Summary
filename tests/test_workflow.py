from datetime import datetime, timedelta, timezone

import pytest

from ai_digest.classifiers.fixed import FixedClassifier
from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft, VALID_CATEGORIES
from ai_digest.workflow import AddArticleWorkflow


CATEGORY = next(iter(VALID_CATEGORIES))
NOW = datetime(2026, 8, 9, 10, 30, tzinfo=timezone(timedelta(hours=8)))


class FakeRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.records = []

    def list(self) -> list[object]:
        self.events.append("duplicate preflight")
        return self.records.copy()

    def save(self, record: object) -> None:
        self.events.append("save")
        self.records.append(record)


class FakeExtractor:
    def __init__(self, events: list[str], result: ExtractedArticle | Exception) -> None:
        self.events = events
        self.result = result

    def extract(self, url: str) -> ExtractedArticle:
        self.events.append("extract")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSummarizer:
    def __init__(self, events: list[str], result: SummaryDraft | Exception) -> None:
        self.events = events
        self.result = result

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        self.events.append("summarize")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClassifier:
    def __init__(self, events: list[str], category: str) -> None:
        self.events = events
        self.category = category
        self.text = ""

    def predict(self, text: str) -> str:
        self.events.append("classify")
        self.text = text
        return self.category


def article() -> ExtractedArticle:
    return ExtractedArticle(
        canonical_url="https://example.com/AI%20news",
        title="AI title",
        author="Author",
        published_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        text="Extracted body.",
    )


def draft() -> SummaryDraft:
    return SummaryDraft(
        summary="Summary text.",
        keyPoints=["Point one", "Point two", "Point three"],
        tags=[" AI ", "ai", "News"],
        editorial="Editorial text.",
    )


def workflow(events: list[str], category: str = CATEGORY) -> tuple[AddArticleWorkflow, FakeRepository, FakeClassifier]:
    repository = FakeRepository(events)
    classifier = FakeClassifier(events, category)
    return (
        AddArticleWorkflow(
            FakeExtractor(events, article()), FakeSummarizer(events, draft()), classifier, repository
        ),
        repository,
        classifier,
    )


def test_workflow_runs_in_order_and_assembles_deterministic_validated_record(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    subject, repository, classifier = workflow(events)
    from ai_digest import workflow as workflow_module

    original_normalize = workflow_module.normalize_public_url
    original_assemble = workflow_module._assemble_payload
    original_validate = workflow_module.SummaryRecord.model_validate

    def normalized(url: str) -> str:
        events.append("normalize")
        return original_normalize(url)

    def assembled(*args: object, **kwargs: object) -> dict[str, object]:
        events.append("assemble")
        return original_assemble(*args, **kwargs)

    def validated(payload: object, *args: object, **kwargs: object) -> object:
        events.append("validate")
        return original_validate(payload, *args, **kwargs)

    monkeypatch.setattr(workflow_module, "normalize_public_url", normalized)
    monkeypatch.setattr(workflow_module, "_assemble_payload", assembled)
    monkeypatch.setattr(workflow_module.SummaryRecord, "model_validate", validated)

    record = subject.run("HTTPS://EXAMPLE.COM/AI%20news?utm_source=x", NOW)

    assert events == ["normalize", "duplicate preflight", "extract", "summarize", "classify", "assemble", "validate", "save"]
    assert record.id == "20260809-ai-title-07bc8395"
    assert record.created_at == NOW
    assert record.updated_at == NOW
    assert record.source_published_at == article().published_at
    assert record.tags == ["AI", "News"]
    assert record.status == "published"
    assert repository.records == [record]
    assert classifier.text == "AI title\nSummary text.\nPoint one\nPoint two\nPoint three"


def test_invalid_classifier_category_fails_before_save() -> None:
    events: list[str] = []
    subject, repository, _ = workflow(events, "not-a-category")

    with pytest.raises(DigestError) as raised:
        subject.run("https://example.com/AI%20news", NOW)

    assert raised.value.stage == "classify"
    assert raised.value.code == "INVALID_CATEGORY"
    assert repository.records == []
    assert events == ["duplicate preflight", "extract", "summarize", "classify"]


@pytest.mark.parametrize("stage", ["extract", "summarize", "classify"])
def test_upstream_errors_leave_repository_empty(stage: str) -> None:
    events: list[str] = []
    repository = FakeRepository(events)
    error = DigestError(stage, "FAILED", "safe", False)
    extractor: object = FakeExtractor(events, error if stage == "extract" else article())
    summarizer: object = FakeSummarizer(events, error if stage == "summarize" else draft())
    classifier: object = FakeClassifier(events, CATEGORY if stage != "classify" else "not-a-category")
    subject = AddArticleWorkflow(extractor, summarizer, classifier, repository)

    with pytest.raises(DigestError):
        subject.run("https://example.com/AI%20news", NOW)

    assert repository.records == []


def test_fixed_classifier_rejects_unknown_development_category() -> None:
    with pytest.raises(DigestError) as raised:
        FixedClassifier("not-a-category")

    assert raised.value.stage == "classify"
    assert raised.value.code == "INVALID_CATEGORY"
