import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

from ai_digest import cli
from ai_digest.cli import create_app
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
