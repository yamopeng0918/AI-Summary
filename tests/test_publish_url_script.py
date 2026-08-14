import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
import sys
from urllib.request import Request
from zoneinfo import ZoneInfo

import pytest

from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES
from ai_digest.publishing import PublishError, PublishResult
from scripts import publish_url


TAIPEI = ZoneInfo("Asia/Taipei")
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
        createdAt=datetime(2026, 8, 14, 10, 0, tzinfo=TAIPEI),
        updatedAt=datetime(2026, 8, 14, 10, 0, tzinfo=TAIPEI),
        summary="Example summary.",
        keyPoints=["First", "Second", "Third"],
        category=CATEGORY,
        tags=["AI"],
        editorial="Editorial note.",
        status="published",
    )


class FakePublisher:
    def __init__(self, result: PublishResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.urls: list[str] = []

    def publish(self, url: str) -> PublishResult:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_main_requires_exactly_one_positional_url_argument(capsys) -> None:
    exit_code = publish_url.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "usage:" in captured.err


def test_main_rejects_extra_positional_arguments(capsys) -> None:
    exit_code = publish_url.main(["https://example.com/one", "https://example.com/two"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "usage:" in captured.err


def test_main_prints_success_output_with_id_commit_workflow_and_detail_url(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    publisher = FakePublisher(
        result=PublishResult(
            record_id="example",
            commit_sha="a" * 40,
            workflow_url="https://github.com/yamopeng0918/AI-Summary/actions/runs/123",
            detail_url="https://yamopeng0918.github.io/AI-Summary/summaries/example/",
        )
    )
    monkeypatch.setattr(publish_url, "_build_publisher", lambda: publisher)

    exit_code = publish_url.main(["https://example.com/article"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload == {
        "id": "example",
        "commit": "a" * 40,
        "workflow": "https://github.com/yamopeng0918/AI-Summary/actions/runs/123",
        "detail": "https://yamopeng0918.github.io/AI-Summary/summaries/example/",
    }
    assert publisher.urls == ["https://example.com/article"]
    assert captured.err == ""


def test_main_reports_publish_error_safely_without_echoing_the_url_or_key(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    secret = "ghp_superSecretToken123"
    url = "https://example.com/private?token=123"
    publisher = FakePublisher(
        error=PublishError("deploy", "local publish failed")
    )
    monkeypatch.setattr(publish_url, "_build_publisher", lambda: publisher)

    exit_code = publish_url.main([url])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.err) == {
        "stage": "deploy",
        "message": "local publish failed",
    }
    assert url not in captured.err
    assert secret not in captured.err
    assert captured.out == ""


def test_main_reports_digest_error_safely_without_echoing_the_url_or_key(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    secret = "sk-proj-SECRET1234567890"
    url = "https://example.com/public-article"
    publisher = FakePublisher(
        error=DigestError("input", "FAILED", "safe input failure", False)
    )
    monkeypatch.setattr(publish_url, "_build_publisher", lambda: publisher)

    exit_code = publish_url.main([url])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.err) == {
        "stage": "input",
        "code": "FAILED",
        "message": "safe input failure",
        "retryable": False,
    }
    assert url not in captured.err
    assert secret not in captured.err
    assert captured.out == ""


def test_run_command_uses_subprocess_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = publish_url._run_command(["git", "status"], Path("C:/workspace"))

    assert result.returncode == 0
    assert result.stdout == b"ok"
    assert result.stderr == ""
    assert captured["command"] == ["git", "status"]
    assert captured["kwargs"] == {
        "cwd": Path("C:/workspace"),
        "capture_output": True,
        "check": False,
        "text": False,
        "shell": False,
    }


def test_fetch_json_uses_the_fixed_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"workflow_runs": []}'

    def fake_urlopen(request: Request, timeout: float):
        captured["user_agent"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(publish_url, "urlopen", fake_urlopen)

    payload = publish_url._fetch_json("https://example.com/api")

    assert payload == {"workflow_runs": []}
    assert captured == {
        "user_agent": publish_url.USER_AGENT,
        "timeout": publish_url.REQUEST_TIMEOUT_SECONDS,
    }


def test_fetch_json_rejects_non_200_responses_without_exposing_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publish_url,
        "_request",
        lambda _url: (503, b'{"token":"secret"}'),
    )

    with pytest.raises(RuntimeError) as raised:
        publish_url._fetch_json("https://example.com/api")

    assert str(raised.value) == "request failed"
    assert "secret" not in str(raised.value)


def test_build_publisher_uses_fixed_defaults_and_existing_cli_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record("created")
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

        def run(self, url: str, now: datetime) -> SummaryRecord:
            captured["run"] = (url, now)
            return record

    monkeypatch.setattr(publish_url.cli, "AddArticleWorkflow", FakeWorkflow)
    monkeypatch.setattr(publish_url.cli, "WebExtractor", lambda client_factory: ("extractor", client_factory))
    monkeypatch.setattr(publish_url.cli, "FixedClassifier", lambda category: ("classifier", category))
    monkeypatch.setattr(publish_url.cli, "_summarizer", lambda: "summarizer")
    monkeypatch.setattr(
        publish_url.cli,
        "_now",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=TAIPEI),
    )

    publisher = publish_url._build_publisher()
    created = publisher.add_summary("https://example.com/article")

    assert created == record
    assert publisher.repository.root == Path("data/summaries")
    assert publisher.config.repository_root == Path(publish_url.__file__).resolve().parents[1]
    assert publisher.config.summary_root == Path(publish_url.__file__).resolve().parents[1] / "data" / "summaries"
    assert publisher.config.site_root == "https://yamopeng0918.github.io/AI-Summary/"
    assert publisher.config.github_repository == "yamopeng0918/AI-Summary"
    assert publisher.config.workflow_name == "Deploy to GitHub Pages"
    assert captured["repository"] is publisher.repository
    assert captured["summarizer"] == "summarizer"
    assert captured["run"] == (
        "https://example.com/article",
        datetime(2026, 8, 14, 12, 0, tzinfo=TAIPEI),
    )


def test_build_publisher_uses_one_script_owned_repository_for_workflow_save_and_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record("created")
    script_repository_root = Path("data/summaries")
    env_repository_root = Path("C:/elsewhere/summaries")
    captured: dict[str, object] = {}

    class FakeRepository:
        def __init__(self, root: Path) -> None:
            self.root = root
            self._records: list[SummaryRecord] = []

        def save(self, saved_record: SummaryRecord) -> None:
            self._records.append(saved_record)

        def list(self) -> list[SummaryRecord]:
            return list(self._records)

    fake_repository = FakeRepository(script_repository_root)

    class FakeWorkflow:
        def __init__(self, **dependencies: object) -> None:
            captured.update(dependencies)

        def run(self, url: str, now: datetime) -> SummaryRecord:
            captured["run"] = (url, now)
            repository = captured["repository"]
            assert isinstance(repository, FakeRepository)
            repository.save(record)
            return record

    monkeypatch.setenv("AI_DIGEST_SUMMARY_ROOT", os.fspath(env_repository_root))
    monkeypatch.setattr(publish_url, "SummaryRepository", lambda path: fake_repository)
    monkeypatch.setattr(publish_url.cli, "AddArticleWorkflow", FakeWorkflow)
    monkeypatch.setattr(publish_url.cli, "WebExtractor", lambda client_factory: ("extractor", client_factory))
    monkeypatch.setattr(publish_url.cli, "FixedClassifier", lambda category: ("classifier", category))
    monkeypatch.setattr(publish_url.cli, "_summarizer", lambda: "summarizer")
    monkeypatch.setattr(
        publish_url.cli,
        "_now",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=TAIPEI),
    )

    publisher = publish_url._build_publisher()
    created = publisher.add_summary("https://example.com/article")

    assert created == record
    assert publisher.repository is fake_repository
    assert captured["repository"] is fake_repository
    assert publisher.repository.root == script_repository_root
    assert publisher.repository.root != env_repository_root
    assert publisher.repository.list() == [record]


def test_script_starts_by_file_path_in_a_clean_subprocess_without_module_errors() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "publish_url.py"

    result = subprocess.run(
        [sys.executable, "-I", str(script_path), "--help"],
        cwd=script_path.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Publish one public article URL to AI Digest." in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
