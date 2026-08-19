import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from ai_digest import cli
from ai_digest.cli import create_app
from ai_digest.classifiers.evaluation import (
    CategoryCounts,
    CategoryMetrics,
    EvaluationResult,
    SplitAssignment,
)
from ai_digest.classifiers.service import ClassifierEvaluationService
from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES
from ai_digest.storage import SummaryRepository


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 9, 14, 0, tzinfo=TAIPEI)
CATEGORY = next(iter(VALID_CATEGORIES))


def make_record(record_id: str = "example") -> SummaryRecord:
    return SummaryRecord(
        schemaVersion=1,
        id=record_id,
        canonicalUrl=f"https://example.com/{record_id}",
        sourceType="web",
        title="Example title",
        author=None,
        sourcePublishedAt=None,
        createdAt=NOW,
        updatedAt=NOW,
        summary="Example summary.",
        keyPoints=["First", "Second", "Third"],
        category=CATEGORY,
        tags=["AI"],
        editorial="Editorial note.",
        status="published",
    )


class FakeWorkflow:
    def __init__(
        self,
        result: SummaryRecord | None = None,
        error: DigestError | None = None,
        stages: tuple[str, ...] = ("input", "extract", "summarize", "classify", "validate", "save"),
    ) -> None:
        self.result = result
        self.error = error
        self.urls: list[str] = []
        self.stages = stages
        self.on_progress = None

    def run(self, url: str, now: datetime) -> SummaryRecord:
        self.urls.append(url)
        for stage in self.stages:
            if self.on_progress is not None:
                self.on_progress(stage)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def make_app(tmp_path: Path, workflow: FakeWorkflow):
    repository = SummaryRepository(tmp_path)
    def workflow_factory(on_progress):
        workflow.on_progress = on_progress
        return workflow

    return create_app(workflow_factory, lambda: repository, lambda: NOW), repository


def make_evaluation_result() -> EvaluationResult:
    category_counts = tuple(CategoryCounts(category, train=24, test=6) for category in sorted(VALID_CATEGORIES))
    category_metrics = tuple(
        CategoryMetrics(category, precision=0.8, recall=0.8, f1=0.8, support=6)
        for category in sorted(VALID_CATEGORIES)
    )
    return EvaluationResult(
        dataset_sha256="a" * 64,
        split_sha256="b" * 64,
        seed=42,
        train_samples=144,
        test_samples=36,
        category_counts=category_counts,
        accuracy=0.8,
        macro_f1=0.79,
        category_metrics=category_metrics,
        confusion_matrix=tuple(tuple(int(row == column) * 6 for column in range(6)) for row in range(6)),
        majority_baseline_accuracy=1 / 6,
        beats_baseline=True,
        evaluated_at=NOW.isoformat(),
        evaluation_pipeline=object(),
    )


class FakeEvaluationService:
    def __init__(self, result: EvaluationResult | None = None, error: DigestError | None = None) -> None:
        self.result = result
        self.error = error
        self.run_calls = 0

    def run(self) -> EvaluationResult:
        self.run_calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def cli_payload(self, result: EvaluationResult) -> dict[str, object]:
        assert result is self.result
        return {
            "accuracy": result.accuracy,
            "macroF1": result.macro_f1,
            "majorityBaselineAccuracy": result.majority_baseline_accuracy,
            "beatsBaseline": result.beats_baseline,
            "datasetPath": "data/classifier/training.csv",
            "categoryPath": "data/categories.json",
            "splitPath": "data/classifier/split.json",
            "reportPath": "data/classifier/evaluation.json",
            "modelPath": "models/classifier.joblib",
            "manifestPath": "models/classifier-manifest.json",
        }


def test_add_reports_all_pipeline_stages_and_saved_location(tmp_path) -> None:
    app, _ = make_app(tmp_path, FakeWorkflow(make_record()))

    result = CliRunner().invoke(app, ["add", "https://example.com/article"])

    assert result.exit_code == 0
    for stage in ("input", "extract", "summarize", "classify", "validate", "save", "complete"):
        assert f'"stage": "{stage}"' in result.stdout
    assert "example" in result.stdout
    assert json.loads(result.stdout.splitlines()[-1])["path"] == str(tmp_path / "example.json")


def test_add_stops_reporting_progress_after_an_early_failure(tmp_path) -> None:
    error = DigestError("extract", "FAILED", "safe", False)
    app, _ = make_app(tmp_path, FakeWorkflow(error=error, stages=("input", "extract")))

    result = CliRunner().invoke(app, ["add", "https://example.com/article"])

    assert result.exit_code == 1
    assert [json.loads(line)["stage"] for line in result.stdout.splitlines()] == [
        "input",
        "extract",
    ]
    assert "summarize" not in result.stdout


def test_add_reports_public_domain_errors_to_stderr(tmp_path) -> None:
    error = DigestError("input", "INVALID_URL", "URL must be public", False)
    app, _ = make_app(tmp_path, FakeWorkflow(error=error))

    result = CliRunner().invoke(app, ["add", "not-a-url"])

    assert result.exit_code == 1
    assert "URL must be public" in result.stderr
    assert "not-a-url" not in result.stderr


def test_evaluate_classifier_emits_metrics_and_artifact_paths(tmp_path: Path) -> None:
    repository = SummaryRepository(tmp_path)
    evaluation_service = FakeEvaluationService(result=make_evaluation_result())
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: repository,
        lambda: NOW,
        evaluation_service_factory=lambda: evaluation_service,
    )

    result = CliRunner().invoke(app, ["evaluate-classifier"])

    assert result.exit_code == 0
    assert evaluation_service.run_calls == 1
    assert json.loads(result.stdout) == {
        "accuracy": 0.8,
        "macroF1": 0.79,
        "majorityBaselineAccuracy": 1 / 6,
        "beatsBaseline": True,
        "datasetPath": "data/classifier/training.csv",
        "categoryPath": "data/categories.json",
        "splitPath": "data/classifier/split.json",
        "reportPath": "data/classifier/evaluation.json",
        "modelPath": "models/classifier.joblib",
        "manifestPath": "models/classifier-manifest.json",
    }


@pytest.mark.parametrize(
    "error",
    (
        DigestError(
            "classify",
            "EVALUATION_BELOW_BASELINE",
            "Classifier evaluation did not beat the majority baseline",
            False,
        ),
        DigestError("classify", "INVALID_DATASET", "Classifier dataset is invalid", False),
    ),
)
def test_evaluate_classifier_reports_domain_failures_as_json_on_stderr(
    tmp_path: Path,
    error: DigestError,
) -> None:
    repository = SummaryRepository(tmp_path)
    evaluation_service = FakeEvaluationService(error=error)
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: repository,
        lambda: NOW,
        evaluation_service_factory=lambda: evaluation_service,
    )

    result = CliRunner().invoke(app, ["evaluate-classifier"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == error.as_dict()


def test_evaluate_classifier_hides_evaluation_artifact_persistence_details(
    tmp_path: Path,
) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    categories = tuple(sorted(VALID_CATEGORIES))
    split = SplitAssignment(
        seed=42,
        dataset_sha256="a" * 64,
        train_ids=("train",),
        test_ids=("test",),
        category_counts=tuple(CategoryCounts(category, train=1, test=1) for category in categories),
    )
    split_path = tmp_path / "classifier" / "split.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text(json.dumps(split.as_dict()), encoding="utf-8")
    report_path = tmp_path / "private" / "evaluation.json"

    def persistence_failure(path: Path, payload: object) -> None:
        assert path == report_path
        raise OSError(f"RAW_PERSISTENCE_MARKER: {path.resolve()}")

    evaluation_service = ClassifierEvaluationService(
        clock=lambda: NOW,
        split_path=split_path,
        report_path=report_path,
        category_loader=lambda path: categories,
        dataset_loader=lambda path, configured: [object()],
        cohort_selector=lambda examples, configured, count: [object()],
        split_creator=lambda examples, configured, **options: split,
        evaluator=lambda examples, assignment, configured, **options: make_evaluation_result(),
        json_writer=persistence_failure,
        model_saver=lambda *args: None,
    )
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: repository,
        lambda: NOW,
        evaluation_service_factory=lambda: evaluation_service,
    )

    result = CliRunner().invoke(app, ["evaluate-classifier"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "stage": "classify",
        "code": "INVALID_DATASET",
        "message": "Classifier evaluation artifacts could not be saved",
        "retryable": False,
    }
    assert "RAW_PERSISTENCE_MARKER" not in result.stderr
    assert str(report_path.resolve()) not in result.stderr


def test_evaluate_classifier_hides_model_persistence_details(tmp_path: Path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    categories = tuple(sorted(VALID_CATEGORIES))
    split = SplitAssignment(
        seed=42,
        dataset_sha256="a" * 64,
        train_ids=("train",),
        test_ids=("test",),
        category_counts=tuple(CategoryCounts(category, train=1, test=1) for category in categories),
    )
    split_path = tmp_path / "classifier" / "split.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text(json.dumps(split.as_dict()), encoding="utf-8")
    model_path = tmp_path / "private" / "classifier.joblib"

    def model_persistence_failure(
        examples,
        evaluation,
        configured,
        configured_model_path: Path,
        manifest_path: Path,
        trained_at: datetime,
    ) -> None:
        assert configured_model_path == model_path
        raise OSError(f"RAW_MODEL_PERSISTENCE_MARKER: {configured_model_path.resolve()}")

    evaluation_service = ClassifierEvaluationService(
        clock=lambda: NOW,
        split_path=split_path,
        report_path=tmp_path / "classifier" / "evaluation.json",
        model_path=model_path,
        manifest_path=tmp_path / "private" / "classifier-manifest.json",
        category_loader=lambda path: categories,
        dataset_loader=lambda path, configured: [object()],
        cohort_selector=lambda examples, configured, count: [object()],
        split_creator=lambda examples, configured, **options: split,
        evaluator=lambda examples, assignment, configured, **options: make_evaluation_result(),
        json_writer=lambda path, payload: None,
        model_saver=model_persistence_failure,
    )
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: repository,
        lambda: NOW,
        evaluation_service_factory=lambda: evaluation_service,
    )

    result = CliRunner().invoke(app, ["evaluate-classifier"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "stage": "classify",
        "code": "PREDICTION_FAILED",
        "message": "Classifier model could not be saved",
        "retryable": False,
    }
    assert "RAW_MODEL_PERSISTENCE_MARKER" not in result.stderr
    assert str(model_path.resolve()) not in result.stderr


def test_list_prints_id_title_category_and_status(tmp_path) -> None:
    app, repository = make_app(tmp_path, FakeWorkflow(make_record()))
    repository.save(make_record())

    result = CliRunner().invoke(app, ["list"])

    assert result.exit_code == 0
    assert "example" in result.stdout
    assert "Example title" in result.stdout
    assert CATEGORY in result.stdout
    assert "published" in result.stdout


def test_show_emits_valid_summary_json(tmp_path) -> None:
    app, repository = make_app(tmp_path, FakeWorkflow(make_record()))
    repository.save(make_record())

    result = CliRunner().invoke(app, ["show", "example"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == make_record().model_dump(mode="json", by_alias=True)


def test_archive_and_publish_change_status_without_changing_content(tmp_path) -> None:
    app, repository = make_app(tmp_path, FakeWorkflow(make_record()))
    original = make_record()
    repository.save(original)
    runner = CliRunner()

    archived = runner.invoke(app, ["archive", "example"])
    archived_record = repository.get("example")
    published = runner.invoke(app, ["publish", "example"])
    published_record = repository.get("example")

    assert archived.exit_code == 0
    assert archived_record.status == "archived"
    assert archived_record.model_dump(exclude={"status", "updated_at"}) == original.model_dump(
        exclude={"status", "updated_at"}
    )
    assert published.exit_code == 0
    assert published_record.status == "published"
    assert published_record.model_dump(exclude={"status", "updated_at"}) == original.model_dump(
        exclude={"status", "updated_at"}
    )


def test_production_app_keeps_local_commands_available_without_a_provider_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AI_DIGEST_PROVIDER", raising=False)
    monkeypatch.setenv("AI_DIGEST_SUMMARY_ROOT", str(tmp_path))
    repository = SummaryRepository(tmp_path)
    repository.save(make_record())
    runner = CliRunner()

    listed = runner.invoke(cli.app, ["list"])
    shown = runner.invoke(cli.app, ["show", "example"])
    archived = runner.invoke(cli.app, ["archive", "example"])
    published = runner.invoke(cli.app, ["publish", "example"])
    added = runner.invoke(cli.app, ["add", "https://example.com/article"])

    assert listed.exit_code == 0
    assert "example" in listed.stdout
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["id"] == "example"
    assert archived.exit_code == 0
    assert published.exit_code == 0
    assert repository.get("example").status == "published"
    assert added.exit_code == 1
    assert json.loads(added.stderr) == {
        "stage": "input",
        "code": "MISSING_API_KEY",
        "message": "GEMINI_API_KEY is required for add",
        "retryable": False,
    }


def test_production_evaluate_classifier_is_key_free_and_does_not_construct_provider_clients(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    evaluation_service = FakeEvaluationService(result=make_evaluation_result())
    captured: dict[str, object] = {}

    def service_factory(*, clock):
        captured["clock"] = clock
        return evaluation_service

    def unexpected_provider(*args, **kwargs):
        raise AssertionError("evaluate-classifier must not construct a provider client")

    monkeypatch.setattr(cli, "ClassifierEvaluationService", service_factory)
    monkeypatch.setattr(cli, "OpenAI", unexpected_provider)
    monkeypatch.setattr(cli.genai, "Client", unexpected_provider)

    result = CliRunner().invoke(cli.app, ["evaluate-classifier"])

    assert result.exit_code == 0
    assert captured["clock"] is cli._now
    assert evaluation_service.run_calls == 1


def test_create_app_default_evaluation_service_uses_its_injected_clock(monkeypatch) -> None:
    evaluation_service = FakeEvaluationService(result=make_evaluation_result())
    captured: dict[str, object] = {}

    def injected_clock() -> datetime:
        return NOW

    def service_factory(*, clock):
        captured["clock"] = clock
        return evaluation_service

    monkeypatch.setattr(cli, "ClassifierEvaluationService", service_factory)
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(Path("unused")),
        injected_clock,
    )

    result = CliRunner().invoke(app, ["evaluate-classifier"])

    assert result.exit_code == 0
    assert captured["clock"] is injected_clock


def test_production_defaults_to_gemini_and_keeps_web_extractor_wiring(monkeypatch) -> None:
    assert cli._repository().root == Path("data/summaries")
    monkeypatch.delenv("AI_DIGEST_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

    class FakeGeminiClient:
        def __init__(self, *, api_key: str) -> None:
            captured["gemini_api_key"] = api_key

    class FakeGeminiSummarizer:
        def __init__(self, client: object, model: str) -> None:
            captured["gemini_client"] = client
            captured["summarizer_model"] = model

    monkeypatch.setattr(cli, "AddArticleWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "genai", type("FakeGenAI", (), {"Client": FakeGeminiClient}), raising=False)
    monkeypatch.setattr(cli, "GeminiSummarizer", FakeGeminiSummarizer, raising=False)

    cli._workflow()

    extractor = captured["extractor"]
    assert isinstance(extractor, cli.WebExtractor)
    assert extractor._client_factory is cli._web_client_factory
    assert captured["gemini_api_key"] == "test-key"
    assert captured["summarizer_model"] == "gemini-3.6-flash"


def test_production_can_select_openai(monkeypatch) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

    class FakeOpenAISummarizer:
        def __init__(self, client: object, model: str) -> None:
            captured["openai_client"] = client
            captured["summarizer_model"] = model

    monkeypatch.setattr(cli, "AddArticleWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "OpenAI", lambda *, api_key: captured.update(openai_api_key=api_key))
    monkeypatch.setattr(cli, "OpenAISummarizer", FakeOpenAISummarizer)

    cli._workflow()

    assert captured["openai_api_key"] == "test-key"
    assert captured["summarizer_model"] == "gpt-5-mini"


def test_unknown_provider_is_rejected_without_creating_a_client(monkeypatch) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "anthropic")

    try:
        cli._workflow()
    except DigestError as error:
        assert error.as_dict() == {
            "stage": "input",
            "code": "INVALID_PROVIDER",
            "message": "AI_DIGEST_PROVIDER must be gemini or openai",
            "retryable": False,
        }
    else:
        raise AssertionError("expected an invalid provider error")


def test_missing_gemini_key_mentions_only_gemini_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-key")

    try:
        cli._workflow()
    except DigestError as error:
        assert error.as_dict() == {
            "stage": "input",
            "code": "MISSING_API_KEY",
            "message": "GEMINI_API_KEY is required for add",
            "retryable": False,
        }
    else:
        raise AssertionError("expected a missing Gemini API key error")


def test_missing_openai_key_mentions_only_openai_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "other-provider-key")

    try:
        cli._workflow()
    except DigestError as error:
        assert error.as_dict() == {
            "stage": "input",
            "code": "MISSING_API_KEY",
            "message": "OPENAI_API_KEY is required for add",
            "retryable": False,
        }
    else:
        raise AssertionError("expected a missing OpenAI API key error")
