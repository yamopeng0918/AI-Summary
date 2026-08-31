import json
import os
from contextlib import contextmanager
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
from ai_digest.classifiers.fixed import FixedClassifier
from ai_digest.classifiers.service import ClassifierEvaluationService
from ai_digest.domain import DigestError, SummaryDraft, SummaryRecord, VALID_CATEGORIES
from ai_digest.storage import SummaryRepository


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 9, 14, 0, tzinfo=TAIPEI)
CATEGORY = next(iter(VALID_CATEGORIES))


class RecordingTextStream:
    def __init__(self, *, tty: bool, supports_reconfigure: bool = True) -> None:
        self.tty = tty
        self.encoding = "cp950"
        self.reconfigure_calls: list[dict[str, str]] = []
        if not supports_reconfigure:
            self.reconfigure = None  # type: ignore[assignment]

    def isatty(self) -> bool:
        return self.tty

    def reconfigure(self, **kwargs: str) -> None:
        self.reconfigure_calls.append(kwargs)
        self.encoding = kwargs["encoding"]


def test_windows_interactive_stream_is_reconfigured_to_utf8() -> None:
    stream = RecordingTextStream(tty=True)

    cli._configure_windows_utf8(stream, platform="win32")

    assert stream.encoding == "utf-8"
    assert stream.reconfigure_calls == [{"encoding": "utf-8"}]


def test_non_windows_stream_is_not_reconfigured() -> None:
    stream = RecordingTextStream(tty=True)

    cli._configure_windows_utf8(stream, platform="linux")

    assert stream.encoding == "cp950"
    assert stream.reconfigure_calls == []


def test_redirected_windows_stream_is_not_reconfigured() -> None:
    stream = RecordingTextStream(tty=False)

    cli._configure_windows_utf8(stream, platform="win32")

    assert stream.encoding == "cp950"
    assert stream.reconfigure_calls == []


def test_windows_tty_without_reconfigure_is_ignored() -> None:
    stream = RecordingTextStream(tty=True, supports_reconfigure=False)

    cli._configure_windows_utf8(stream, platform="win32")

    assert stream.encoding == "cp950"


def test_windows_tty_with_uninspectable_state_is_ignored() -> None:
    class UninspectableStream:
        def isatty(self) -> bool:
            raise OSError("stream closed")

    cli._configure_windows_utf8(UninspectableStream(), platform="win32")  # type: ignore[arg-type]


def test_list_and_show_preserve_unicode_after_windows_tty_configuration(
    tmp_path, monkeypatch
) -> None:
    title = "Unicode \u7ea7 title"
    with pytest.raises(UnicodeEncodeError):
        title.encode("cp950")

    record = make_record().model_copy(update={"title": title})
    app, repository = make_app(tmp_path, FakeWorkflow(record))
    repository.save(record)
    console = RecordingTextStream(tty=True)
    emitted: list[str] = []
    cli._configure_windows_utf8(console, platform="win32")

    def encoded_echo(message: str, *, err: bool = False) -> None:
        str(message).encode(console.encoding)
        emitted.append(str(message))

    monkeypatch.setattr(cli.typer, "echo", encoded_echo)
    runner = CliRunner()

    listed = runner.invoke(app, ["list"])
    shown = runner.invoke(app, ["show", record.id])

    assert listed.exit_code == 0
    assert shown.exit_code == 0
    assert title in emitted[0]
    assert json.loads(emitted[1])["title"] == title


def test_main_configures_both_streams_before_invoking_app(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    stdout = object()
    stderr = object()
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(
        cli,
        "_configure_windows_utf8",
        lambda stream, *, platform: events.append(("configure", stream, platform)),
    )
    monkeypatch.setattr(cli, "app", lambda: events.append(("app",)))

    cli.main()

    assert events == [
        ("configure", stdout, "win32"),
        ("configure", stderr, "win32"),
        ("app",),
    ]


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


class FakeEditWorkflow:
    def __init__(
        self,
        result: SummaryRecord | None = None,
        error: DigestError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.record_ids: list[str] = []

    def run(self, record_id: str) -> SummaryRecord:
        self.record_ids.append(record_id)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeRegenerateWorkflow:
    def __init__(
        self,
        result: SummaryRecord | None = None,
        error: DigestError | None = None,
        stages: tuple[str, ...] = ("input", "extract", "summarize", "classify", "validate", "save"),
    ) -> None:
        self.result = result
        self.error = error
        self.stages = stages
        self.calls: list[tuple[str, datetime]] = []
        self.on_progress = None

    def run(self, record_id: str, now: datetime) -> SummaryRecord:
        self.calls.append((record_id, now))
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


def make_editing_app(
    tmp_path: Path,
    edit_workflow: FakeEditWorkflow,
    regenerate_workflow: FakeRegenerateWorkflow,
):
    repository = SummaryRepository(tmp_path)

    def regenerate_factory(on_progress):
        regenerate_workflow.on_progress = on_progress
        return regenerate_workflow

    return create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: repository,
        lambda: NOW,
        edit_workflow_factory=lambda: edit_workflow,
        regenerate_workflow_factory=regenerate_factory,
    )


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


def test_edit_runs_injected_workflow_and_reports_saved_location(tmp_path) -> None:
    edit_workflow = FakeEditWorkflow(make_record("edited"))
    app = make_editing_app(tmp_path, edit_workflow, FakeRegenerateWorkflow(make_record()))

    result = CliRunner().invoke(app, ["edit", "edited"])

    assert result.exit_code == 0
    assert edit_workflow.record_ids == ["edited"]
    assert json.loads(result.stdout) == {
        "stage": "complete",
        "id": "edited",
        "path": str(tmp_path / "edited.json"),
    }


def test_regenerate_runs_injected_workflow_with_progress_and_reports_saved_location(
    tmp_path,
) -> None:
    regenerate_workflow = FakeRegenerateWorkflow(make_record("regenerated"))
    app = make_editing_app(tmp_path, FakeEditWorkflow(make_record()), regenerate_workflow)

    result = CliRunner().invoke(app, ["regenerate", "regenerated"])

    assert result.exit_code == 0
    assert regenerate_workflow.calls == [("regenerated", NOW)]
    payloads = [json.loads(line) for line in result.stdout.splitlines()]
    assert [payload["stage"] for payload in payloads] == [
        "input",
        "extract",
        "summarize",
        "classify",
        "validate",
        "save",
        "complete",
    ]
    assert payloads[-1] == {
        "stage": "complete",
        "id": "regenerated",
        "path": str(tmp_path / "regenerated.json"),
    }


@pytest.mark.parametrize("command", ["edit", "regenerate"])
def test_edit_and_regenerate_report_domain_errors_to_stderr(tmp_path, command: str) -> None:
    error = DigestError("save", "INVALID_RECORD", "Summary record is invalid", False)
    app = make_editing_app(
        tmp_path,
        FakeEditWorkflow(error=error),
        FakeRegenerateWorkflow(error=error, stages=()),
    )

    result = CliRunner().invoke(app, [command, "example"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == error.as_dict()


def test_json_events_are_safe_for_non_utf8_windows_consoles(monkeypatch) -> None:
    emitted: list[str] = []

    def cp950_echo(message: str, *, err: bool = False) -> None:
        message.encode("cp950")
        emitted.append(message)

    monkeypatch.setattr(cli.typer, "echo", cp950_echo)

    cli._emit({"stage": "complete", "id": "unicode-级"})

    assert json.loads(emitted[0]) == {"stage": "complete", "id": "unicode-级"}


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


def test_production_edit_is_key_free_and_constructs_no_source_or_provider_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AI_DIGEST_SUMMARY_ROOT", str(tmp_path))
    SummaryRepository(tmp_path).save(make_record())

    class NoOpEditor:
        def edit(self, path: Path) -> None:
            assert path.suffix == ".json"

    def unexpected_dependency(*args, **kwargs):
        raise AssertionError("edit must not construct source or provider dependencies")

    monkeypatch.setattr(cli, "_provider", unexpected_dependency)
    monkeypatch.setattr(cli, "_summarizer", unexpected_dependency)
    monkeypatch.setattr(cli, "_classifier", unexpected_dependency)
    monkeypatch.setattr(cli, "ExtractorRouter", unexpected_dependency)
    monkeypatch.setattr(cli, "WebExtractor", unexpected_dependency)
    monkeypatch.setattr(cli, "OpenAI", unexpected_dependency)
    monkeypatch.setattr(cli.genai, "Client", unexpected_dependency)
    monkeypatch.setattr(cli, "_editor_runner", lambda: NoOpEditor())

    result = CliRunner().invoke(cli.app, ["edit", "example"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "stage": "complete",
        "id": "example",
        "path": str(tmp_path / "example.json"),
    }


def test_editor_runner_injects_process_environment_platform_and_subprocess_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeEditorRunner:
        def __init__(self, environment, *, platform, command_runner) -> None:
            captured.update(
                environment=environment,
                platform=platform,
                command_runner=command_runner,
            )

    def fake_run(*args, **kwargs):
        raise AssertionError("runner must not execute during composition")

    monkeypatch.setattr(cli, "EditorRunner", FakeEditorRunner)
    monkeypatch.setattr(cli.sys, "platform", "test-platform")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    runner = cli._editor_runner()

    assert isinstance(runner, FakeEditorRunner)
    assert captured == {
        "environment": os.environ,
        "platform": "test-platform",
        "command_runner": fake_run,
    }


def test_production_regenerate_defaults_to_gemini_and_wires_add_source_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_DIGEST_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

    class FakeGeminiClient:
        def __init__(self, *, api_key: str) -> None:
            captured["api_key"] = api_key

    class FakeGeminiSummarizer:
        def __init__(self, client: object, model: str) -> None:
            captured["summarizer_client"] = client
            captured["summarizer_model"] = model

    monkeypatch.setattr(cli, "RegenerateSummaryWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "_classifier", lambda: "trained-classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")
    monkeypatch.setattr(cli.genai, "Client", FakeGeminiClient)
    monkeypatch.setattr(cli, "GeminiSummarizer", FakeGeminiSummarizer)

    cli._regenerate_workflow(on_progress=lambda stage: None)

    router = captured["extractor"]
    assert isinstance(router, cli.ExtractorRouter)
    assert isinstance(router._web, cli.WebExtractor)
    assert router._web._client_factory is cli._web_client_factory
    assert isinstance(router._youtube, cli.LazyExtractor)
    assert isinstance(router._bluesky, cli.BlueskyExtractor)
    assert captured["api_key"] == "gemini-key"
    assert captured["summarizer_model"] == "gemini-3.6-flash"
    assert captured["classifier"] == "trained-classifier"
    assert captured["repository"] == "repository"
    assert callable(captured["on_progress"])


def test_regenerate_uses_a_falsey_repository_factory_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = object()
    captured: dict[str, object] = {}

    class FalseyRepositoryFactory:
        def __bool__(self) -> bool:
            return False

        def __call__(self) -> object:
            return repository

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

    def unexpected_default_repository() -> object:
        raise AssertionError("the supplied repository factory must be used")

    def fake_summarizer(provider: object, *, operation: str) -> str:
        captured["summarizer_operation"] = operation
        return "summarizer"

    monkeypatch.setattr(cli, "RegenerateSummaryWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "_provider", lambda: "provider")
    monkeypatch.setattr(cli, "_summarizer", fake_summarizer)
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", unexpected_default_repository)

    cli._regenerate_workflow(repository_factory=FalseyRepositoryFactory())

    assert captured["repository"] is repository
    assert captured["summarizer_operation"] == "regenerate"


def test_production_regenerate_openai_constructs_only_openai_provider_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-must-not-be-used")
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

    class FakeOpenAISummarizer:
        def __init__(self, client: object, model: str) -> None:
            captured["summarizer_client"] = client
            captured["summarizer_model"] = model

    def unexpected_gemini(*args, **kwargs):
        raise AssertionError("OpenAI selection must not construct Gemini dependencies")

    monkeypatch.setattr(cli, "RegenerateSummaryWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "OpenAI", lambda *, api_key: captured.update(api_key=api_key))
    monkeypatch.setattr(cli, "OpenAISummarizer", FakeOpenAISummarizer)
    monkeypatch.setattr(cli.genai, "Client", unexpected_gemini)
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")
    monkeypatch.setattr(
        cli,
        "_youtube_extractor",
        lambda provider: captured.update(youtube_provider=provider) or "youtube-extractor",
    )

    cli._regenerate_workflow()
    youtube = captured["extractor"]._youtube._factory()

    assert captured["api_key"] == "openai-key"
    assert captured["summarizer_model"] == "gpt-5-mini"
    assert captured["youtube_provider"] == "openai"
    assert youtube == "youtube-extractor"


@pytest.mark.parametrize(
    ("provider", "missing_key", "other_key"),
    [
        ("gemini", "GEMINI_API_KEY", "OPENAI_API_KEY"),
        ("openai", "OPENAI_API_KEY", "GEMINI_API_KEY"),
    ],
)
def test_production_regenerate_missing_selected_key_fails_before_workflow_runs(
    provider: str,
    missing_key: str,
    other_key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_started = False

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            nonlocal workflow_started
            workflow_started = True

    monkeypatch.setenv("AI_DIGEST_PROVIDER", provider)
    monkeypatch.delenv(missing_key, raising=False)
    monkeypatch.setenv(other_key, "other-provider-key")
    monkeypatch.setenv("AI_DIGEST_SUMMARY_ROOT", str(tmp_path))
    monkeypatch.setattr(cli, "RegenerateSummaryWorkflow", FakeWorkflow)

    result = CliRunner().invoke(cli.app, ["regenerate", "example"])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == {
        "stage": "input",
        "code": "MISSING_API_KEY",
        "message": f"{missing_key} is required for regenerate",
        "retryable": False,
    }
    assert workflow_started is False


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


def test_production_defaults_to_gemini_and_wires_source_router(monkeypatch) -> None:
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
    monkeypatch.setattr(cli, "_classifier", lambda: "trained-classifier")
    monkeypatch.setattr(cli, "genai", type("FakeGenAI", (), {"Client": FakeGeminiClient}), raising=False)
    monkeypatch.setattr(cli, "GeminiSummarizer", FakeGeminiSummarizer, raising=False)

    cli._workflow()

    extractor = captured["extractor"]
    assert isinstance(extractor, cli.ExtractorRouter)
    assert isinstance(extractor._web, cli.WebExtractor)
    assert extractor._web._client_factory is cli._web_client_factory
    assert isinstance(extractor._youtube, cli.LazyExtractor)
    assert captured["gemini_api_key"] == "test-key"
    assert captured["summarizer_model"] == "gemini-3.6-flash"
    assert captured["classifier"] == "trained-classifier"


def test_production_wires_bluesky_extractor_with_the_web_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

    class FakeAppViewClient:
        def __init__(self, *, client_factory: object) -> None:
            captured["appview_client_factory"] = client_factory

    class FakeBlueskyExtractor:
        def __init__(self, appview: object) -> None:
            captured["appview"] = appview

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(cli, "AddArticleWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "BlueskyAppViewClient", FakeAppViewClient, raising=False)
    monkeypatch.setattr(cli, "BlueskyExtractor", FakeBlueskyExtractor, raising=False)
    monkeypatch.setattr(cli, "_summarizer", lambda provider: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")

    cli._workflow()

    router = captured["extractor"]
    assert isinstance(router, cli.ExtractorRouter)
    assert isinstance(router._bluesky, FakeBlueskyExtractor)
    assert isinstance(captured["appview"], FakeAppViewClient)
    assert captured["appview_client_factory"] is cli._web_client_factory


def test_ordinary_web_route_does_not_call_bluesky_appview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Web:
        def __init__(self, *, client_factory: object) -> None:
            pass

        def extract(self, url: str) -> str:
            return "web-result"

    class FakeAppViewClient:
        def __init__(self, *, client_factory: object) -> None:
            calls.append("construct")

        def resolve_handle(self, handle: str) -> str:
            calls.append("resolve_handle")
            raise AssertionError("ordinary web must not resolve a Bluesky handle")

        def get_post(self, uri: str) -> dict[str, object]:
            calls.append("get_post")
            raise AssertionError("ordinary web must not fetch a Bluesky post")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(cli, "WebExtractor", Web)
    monkeypatch.setattr(cli, "BlueskyAppViewClient", FakeAppViewClient, raising=False)
    monkeypatch.setattr(cli, "_summarizer", lambda provider: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")

    workflow = cli._workflow()

    assert workflow._extractor.extract("https://example.com/article") == "web-result"
    assert calls == ["construct"]


@pytest.mark.parametrize(
    ("provider", "key_name", "model_name", "default_model"),
    [
        ("gemini", "GEMINI_API_KEY", "GEMINI_TRANSCRIPTION_MODEL", "gemini-3.6-flash"),
        ("openai", "OPENAI_API_KEY", "OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe"),
    ],
)
def test_production_wires_youtube_transcriber_for_selected_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    key_name: str,
    model_name: str,
    default_model: str,
) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", provider)
    monkeypatch.setenv(key_name, f"{provider}-key")
    for name in (
        "AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS",
        "AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS",
        "GEMINI_TRANSCRIPTION_MODEL",
        "OPENAI_TRANSCRIPTION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    captured: dict[str, object] = {}
    factory_calls: list[tuple[str, str | None, str]] = []

    class FakeRunner:
        pass

    class FakeMedia:
        def __init__(self, runner: object, *, max_chunk_bytes: int) -> None:
            captured["media_runner"] = runner
            captured["max_chunk_bytes"] = max_chunk_bytes

        def audio_chunks(self, url: str, chunk_seconds: int):
            raise AssertionError("media must remain lazy")

    class FakeProbe:
        def __init__(self, runner: object) -> None:
            captured["probe_runner"] = runner

    class FakeCaptionClient:
        def __init__(self, *, client_factory: object) -> None:
            captured["caption_factory"] = client_factory

    class FakeYouTubeExtractor:
        def __init__(self, **dependencies: object) -> None:
            captured["youtube"] = dependencies

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured["workflow"] = dependencies

    monkeypatch.setattr(cli, "CommandRunner", FakeRunner)
    monkeypatch.setattr(cli, "YouTubeMediaPipeline", FakeMedia)
    monkeypatch.setattr(cli, "YtDlpMetadataProbe", FakeProbe)
    monkeypatch.setattr(cli, "YouTubeCaptionClient", FakeCaptionClient)
    monkeypatch.setattr(cli, "YouTubeExtractor", FakeYouTubeExtractor)
    monkeypatch.setattr(cli, "AddArticleWorkflow", FakeWorkflow)
    monkeypatch.setattr(cli, "_summarizer", lambda selected: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")
    monkeypatch.setattr(
        cli,
        "lazy_openai_transcriber",
        lambda api_key, model: factory_calls.append(("openai", api_key, model))
        or "openai-transcriber",
    )
    monkeypatch.setattr(
        cli,
        "lazy_gemini_transcriber",
        lambda api_key, model: factory_calls.append(("gemini", api_key, model))
        or "gemini-transcriber",
        raising=False,
    )

    cli._workflow(on_progress=lambda stage: None)
    cli._youtube_extractor(provider)

    youtube = captured["youtube"]
    assert isinstance(youtube, dict)
    assert youtube["max_duration_seconds"] == 7200
    assert youtube["chunk_seconds"] == 600
    assert captured["max_chunk_bytes"] == 24 * 1024 * 1024
    assert captured["probe_runner"] is captured["media_runner"]
    assert captured["caption_factory"] is cli._web_client_factory
    assert factory_calls == []
    assert youtube["transcriber_factory"]() == f"{provider}-transcriber"
    assert factory_calls == [(provider, f"{provider}-key", default_model)]
    workflow = captured["workflow"]
    assert isinstance(workflow, dict)
    router = workflow["extractor"]
    assert isinstance(router, cli.ExtractorRouter)
    assert isinstance(router._youtube, cli.LazyExtractor)


@pytest.mark.parametrize(
    ("provider", "key_name", "other_key", "model_name", "custom_model"),
    [
        (
            "gemini",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_TRANSCRIPTION_MODEL",
            "gemini-custom",
        ),
        (
            "openai",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_TRANSCRIPTION_MODEL",
            "openai-custom",
        ),
    ],
)
def test_no_caption_workflow_uses_only_selected_provider_key_and_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    key_name: str,
    other_key: str,
    model_name: str,
    custom_model: str,
) -> None:
    events: list[tuple[str, object]] = []
    metadata = {
        "id": "dQw4w9WgXcQ",
        "title": "公開影片",
        "channel": "公開頻道",
        "upload_date": "20260820",
        "duration": 120,
        "live_status": "not_live",
        "availability": "public",
        "language": "zh-TW",
        "subtitles": {},
        "automatic_captions": {},
    }

    class FakeProbe:
        def __init__(self, runner: object) -> None:
            pass

        def __call__(self, url: str) -> dict[str, object]:
            return metadata

    class UnusedCaptionClient:
        def __init__(self, *, client_factory: object) -> None:
            pass

    class FakeMedia:
        def __init__(self, runner: object, **kwargs: object) -> None:
            pass

        @contextmanager
        def audio_chunks(self, url: str, chunk_seconds: int):
            events.append(("download", chunk_seconds))
            yield [tmp_path / "chunk.mp3"]

    class FakeTranscriber:
        def transcribe(self, chunks: list[Path]) -> str:
            events.append(("transcribe", chunks))
            return "完整逐字稿" * 80

    class FakeSummarizer:
        def __init__(self, client: object, model: str) -> None:
            events.append(("summarizer", provider))

    def selected_transcriber(api_key: str | None, model: str) -> FakeTranscriber:
        events.append(("transcriber_factory", (provider, api_key, model)))
        return FakeTranscriber()

    def unselected_transcriber(*args: object) -> object:
        raise AssertionError("unselected provider must not be used")

    monkeypatch.setenv("AI_DIGEST_PROVIDER", provider)
    monkeypatch.setenv(key_name, f"{provider}-key")
    monkeypatch.delenv(other_key, raising=False)
    monkeypatch.setenv(model_name, custom_model)
    monkeypatch.setenv("AI_DIGEST_TRANSCRIPTION_MODEL", "wrong-provider-model")
    monkeypatch.setattr(cli, "YtDlpMetadataProbe", FakeProbe)
    monkeypatch.setattr(cli, "YouTubeCaptionClient", UnusedCaptionClient)
    monkeypatch.setattr(cli, "YouTubeMediaPipeline", FakeMedia)
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")
    if provider == "gemini":
        monkeypatch.setattr(cli.genai, "Client", lambda *, api_key: object())
        monkeypatch.setattr(cli, "GeminiSummarizer", FakeSummarizer)
        monkeypatch.setattr(cli, "lazy_gemini_transcriber", selected_transcriber)
        monkeypatch.setattr(cli, "lazy_openai_transcriber", unselected_transcriber)
    else:
        monkeypatch.setattr(cli, "OpenAI", lambda *, api_key: object())
        monkeypatch.setattr(cli, "OpenAISummarizer", FakeSummarizer)
        monkeypatch.setattr(cli, "lazy_openai_transcriber", selected_transcriber)
        monkeypatch.setattr(cli, "lazy_gemini_transcriber", unselected_transcriber)

    workflow = cli._workflow()
    article = workflow._extractor.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert article.source_type == "youtube"
    assert ("summarizer", provider) in events
    assert ("transcriber_factory", (provider, f"{provider}-key", custom_model)) in events
    assert ("download", 600) in events
    assert "wrong-provider-model" not in repr(events)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS", "0"),
        ("AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS", "-1"),
        ("AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS", "abc"),
        ("AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", "0"),
        ("AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", "-1"),
        ("AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", "abc"),
    ],
)
def test_production_rejects_non_positive_youtube_integer_settings(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(DigestError) as raised:
        cli._youtube_extractor("gemini")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "INVALID_CONFIG",
        "message": f"{name} must be a positive integer",
        "retryable": False,
    }


def test_captioned_gemini_youtube_workflow_needs_no_openai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = {
        "id": "dQw4w9WgXcQ",
        "title": "公開影片",
        "channel": "公開頻道",
        "upload_date": "20260820",
        "duration": 120,
        "live_status": "not_live",
        "availability": "public",
        "language": "zh-TW",
        "subtitles": {
            "zh-TW": [
                {"url": "https://captions.example/manual.vtt", "ext": "vtt"}
            ]
        },
        "automatic_captions": {},
    }

    class FakeProbe:
        def __init__(self, runner: object, **kwargs: object) -> None:
            pass

        def __call__(self, url: str) -> dict[str, object]:
            return metadata

    class FakeCaptionClient:
        def __init__(self, *, client_factory: object) -> None:
            pass

        def __call__(self, url: str) -> str:
            return "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + "字幕內容" * 80

    class ForbiddenMedia:
        def __init__(self, runner: object, **kwargs: object) -> None:
            pass

        def audio_chunks(self, url: str, chunk_seconds: int):
            raise AssertionError("captioned video must not download media")

    class FakeGeminiSummarizer:
        def __init__(self, client: object, model: str) -> None:
            assert model == "gemini-3.6-flash"

        def summarize(self, article: object) -> SummaryDraft:
            return SummaryDraft(
                summary="繁體中文摘要",
                keyPoints=["重點一", "重點二", "重點三"],
                tags=["YouTube"],
                editorial="編輯觀點",
            )

    monkeypatch.setenv("AI_DIGEST_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AI_DIGEST_SUMMARY_ROOT", str(tmp_path))
    monkeypatch.setattr(cli, "YtDlpMetadataProbe", FakeProbe)
    monkeypatch.setattr(cli, "YouTubeCaptionClient", FakeCaptionClient)
    monkeypatch.setattr(cli, "YouTubeMediaPipeline", ForbiddenMedia)
    monkeypatch.setattr(cli.genai, "Client", lambda *, api_key: object())
    monkeypatch.setattr(cli, "GeminiSummarizer", FakeGeminiSummarizer)
    monkeypatch.setattr(cli, "_classifier", lambda: FixedClassifier(CATEGORY))

    record = cli._workflow().run(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", NOW
    )

    assert record.source_type == "youtube"
    assert record.title == "公開影片"
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize(
    ("provider", "key_name", "other_key"),
    [
        ("gemini", "GEMINI_API_KEY", "OPENAI_API_KEY"),
        ("openai", "OPENAI_API_KEY", "GEMINI_API_KEY"),
    ],
)
def test_no_caption_missing_selected_provider_key_stops_before_fake_media_download(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    key_name: str,
    other_key: str,
) -> None:
    events: list[str] = []
    metadata = {
        "id": "dQw4w9WgXcQ",
        "title": "公開影片",
        "channel": "公開頻道",
        "upload_date": "20260820",
        "duration": 120,
        "live_status": "not_live",
        "availability": "public",
        "language": "zh-TW",
        "subtitles": {},
        "automatic_captions": {},
    }

    class FakeProbe:
        def __init__(self, runner: object) -> None:
            pass

        def __call__(self, url: str) -> dict[str, object]:
            return metadata

    class UnusedCaptionClient:
        def __init__(self, *, client_factory: object) -> None:
            pass

        def __call__(self, url: str) -> str:
            raise AssertionError("no caption URL should be fetched")

    class RecordingMedia:
        def __init__(self, runner: object, **kwargs: object) -> None:
            pass

        def audio_chunks(self, url: str, chunk_seconds: int):
            events.append("download")
            raise AssertionError("download must not begin without selected provider key")

    monkeypatch.setenv("AI_DIGEST_PROVIDER", provider)
    monkeypatch.delenv(key_name, raising=False)
    monkeypatch.setenv(other_key, "other-provider-key")
    monkeypatch.setattr(cli, "YtDlpMetadataProbe", FakeProbe)
    monkeypatch.setattr(cli, "YouTubeCaptionClient", UnusedCaptionClient)
    monkeypatch.setattr(cli, "YouTubeMediaPipeline", RecordingMedia)
    monkeypatch.setattr(cli, "_summarizer", lambda selected: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")

    workflow = cli._workflow()
    with pytest.raises(DigestError) as raised:
        workflow._extractor.extract(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "MISSING_API_KEY",
        "message": f"{key_name} is required for YouTube audio transcription",
        "retryable": False,
    }
    assert events == []


def test_invalid_youtube_settings_do_not_break_ordinary_web_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", "invalid")
    monkeypatch.setenv("AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS", "invalid")
    monkeypatch.setattr(cli, "_summarizer", lambda provider: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")

    class Web:
        def __init__(self, *, client_factory: object) -> None:
            pass
        def extract(self, url: str) -> str:
            return "web-result"

    monkeypatch.setattr(cli, "WebExtractor", Web)

    workflow = cli._workflow()

    assert workflow._extractor.extract("https://example.com/article") == "web-result"


def test_invalid_youtube_settings_fail_only_when_youtube_route_is_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", "invalid")
    monkeypatch.setattr(cli, "_summarizer", lambda provider: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")

    workflow = cli._workflow()

    with pytest.raises(DigestError) as raised:
        workflow._extractor.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert raised.value.code == "INVALID_CONFIG"
    assert "AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS" in raised.value.message


def test_youtube_chunk_byte_limit_is_validated_when_route_is_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_DIGEST_TRANSCRIPTION_MAX_CHUNK_BYTES", "0")
    monkeypatch.setattr(cli, "_summarizer", lambda provider: "summarizer")
    monkeypatch.setattr(cli, "_classifier", lambda: "classifier")
    monkeypatch.setattr(cli, "_repository", lambda: "repository")
    workflow = cli._workflow()
    with pytest.raises(DigestError) as raised:
        workflow._extractor.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert raised.value.code == "INVALID_CONFIG"
    assert "AI_DIGEST_TRANSCRIPTION_MAX_CHUNK_BYTES" in raised.value.message


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
    monkeypatch.setattr(cli, "_classifier", lambda: "trained-classifier")
    monkeypatch.setattr(cli, "OpenAI", lambda *, api_key: captured.update(openai_api_key=api_key))
    monkeypatch.setattr(cli, "OpenAISummarizer", FakeOpenAISummarizer)

    cli._workflow()

    assert captured["openai_api_key"] == "test-key"
    assert captured["summarizer_model"] == "gpt-5-mini"
    assert captured["classifier"] == "trained-classifier"


def test_production_classifier_uses_only_repository_controlled_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeTrainedClassifier:
        def __init__(self, model_path: Path, manifest_path: Path, categories: tuple[str, ...]) -> None:
            captured["model_path"] = model_path
            captured["manifest_path"] = manifest_path
            captured["categories"] = categories

    monkeypatch.setattr(cli, "TrainedClassifier", FakeTrainedClassifier)

    classifier = cli._classifier()

    assert isinstance(classifier, FakeTrainedClassifier)
    assert captured == {
        "model_path": Path("models/classifier.joblib"),
        "manifest_path": Path("models/classifier-manifest.json"),
        "categories": tuple(json.loads(Path("data/categories.json").read_text(encoding="utf-8"))),
    }


def test_production_add_reports_missing_model_before_workflow_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workflow_started = False

    class FakeWorkflow:
        def __init__(self, **_dependencies: object) -> None:
            nonlocal workflow_started
            workflow_started = True

    monkeypatch.setattr(cli, "TrainedClassifier", lambda *_args: (_ for _ in ()).throw(
        DigestError("classify", "MODEL_NOT_FOUND", "Classifier model artifacts were not found", False)
    ))
    monkeypatch.setattr(cli, "_summarizer", lambda provider: "summarizer")
    monkeypatch.setattr(cli, "AddArticleWorkflow", FakeWorkflow)
    app = create_app(cli._workflow, lambda: SummaryRepository(tmp_path), lambda: NOW)

    result = CliRunner().invoke(app, ["add", "https://example.com/article"])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == {
        "stage": "classify",
        "code": "MODEL_NOT_FOUND",
        "message": "Classifier model artifacts were not found",
        "retryable": False,
    }
    assert workflow_started is False
    assert list(tmp_path.iterdir()) == []


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
