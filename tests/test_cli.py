import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

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
    def __init__(self, result: SummaryRecord | None = None, error: DigestError | None = None) -> None:
        self.result = result
        self.error = error
        self.urls: list[str] = []

    def run(self, url: str, now: datetime) -> SummaryRecord:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def make_app(tmp_path: Path, workflow: FakeWorkflow):
    repository = SummaryRepository(tmp_path)
    return create_app(lambda: workflow, lambda: repository, lambda: NOW), repository


def test_add_reports_all_pipeline_stages_and_saved_location(tmp_path) -> None:
    app, _ = make_app(tmp_path, FakeWorkflow(make_record()))

    result = CliRunner().invoke(app, ["add", "https://example.com/article"])

    assert result.exit_code == 0
    for stage in ("input", "extract", "summarize", "classify", "save", "complete"):
        assert f'"stage": "{stage}"' in result.stdout
    assert "example" in result.stdout
    assert json.loads(result.stdout.splitlines()[-1])["path"] == str(tmp_path / "example.json")


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
