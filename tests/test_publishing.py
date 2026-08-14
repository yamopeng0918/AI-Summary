from pathlib import Path
import sys
from urllib.parse import quote

import pytest

from ai_digest.publishing import (
    CommandResult,
    PublishError,
    PublishingConfig,
    PublishResult,
    SummaryPublisher,
)
from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES


REPOSITORY_ROOT = Path("C:/workspace/AI-Summary")
SUMMARY_ROOT = REPOSITORY_ROOT / "data" / "summaries"
CATEGORY = next(iter(VALID_CATEGORIES))


class FakeRepository:
    def __init__(self, records: list[SummaryRecord]) -> None:
        self._records = records

    def list(self) -> list[SummaryRecord]:
        return list(self._records)


class RecordingRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> CommandResult:
        self.calls.append((command, cwd))
        return self.responses.pop(0)


def result(
    stdout: str | bytes = "", *, returncode: int = 0, stderr: str = ""
) -> CommandResult:
    return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)


def make_record(record_id: str = "example", **changes: object) -> SummaryRecord:
    payload = {
        "schemaVersion": 1,
        "id": record_id,
        "canonicalUrl": f"https://example.com/{record_id}",
        "sourceType": "web",
        "title": "Example title",
        "author": None,
        "sourcePublishedAt": None,
        "createdAt": "2026-08-09T14:00:00+08:00",
        "updatedAt": "2026-08-09T14:00:00+08:00",
        "summary": "An example summary.",
        "keyPoints": ["First point", "Second point", "Third point"],
        "category": CATEGORY,
        "tags": ["AI"],
        "editorial": "Editorial note.",
        "status": "published",
    }
    payload.update(changes)
    return SummaryRecord.model_validate(payload)


def make_publisher(
    runner: RecordingRunner,
    *,
    repository: object | None = None,
    add_summary=None,
    summary_root: Path = SUMMARY_ROOT,
    fetch_json=None,
    fetch_text=None,
    sleep=None,
    now=None,
    poll_attempts: int = 30,
    poll_delay_seconds: float = 10,
) -> SummaryPublisher:
    config = PublishingConfig(
        repository_root=REPOSITORY_ROOT,
        summary_root=summary_root,
        site_root="https://yamopeng0918.github.io/AI-Summary/",
        github_repository="yamopeng0918/AI-Summary",
        workflow_name="Deploy to GitHub Pages",
        poll_attempts=poll_attempts,
        poll_delay_seconds=poll_delay_seconds,
    )
    return SummaryPublisher(
        config=config,
        repository=repository if repository is not None else object(),
        add_summary=add_summary or (lambda _url: None),
        run_command=runner,
        fetch_json=fetch_json or (lambda _url: {}),
        fetch_text=fetch_text or (lambda _url: (200, "")),
        sleep=sleep or (lambda _seconds: None),
        now=now or (lambda: 0),
    )


def expected_commands() -> list[list[str]]:
    return [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "branch", "--show-current"],
        ["git", "status", "--porcelain", "--untracked-files=no"],
        ["git", "fetch", "origin", "master"],
        ["git", "rev-list", "--left-right", "--count", "master...origin/master"],
    ]


def expected_gate_commands() -> list[list[str]]:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    return [
        [sys.executable, "-m", "pytest"],
        [npm, "test"],
        [npm, "run", "build:pages"],
        [
            sys.executable,
            "scripts/verify_deployment.py",
            "--tracked",
            "--dist",
            "site/dist",
            "--base",
            "/AI-Summary/",
        ],
    ]


def test_preflight_checks_clean_master_repository_in_order() -> None:
    runner = RecordingRunner(
        [
            result(str(REPOSITORY_ROOT)),
            result("master\n"),
            result(),
            result(),
            result("0\t0\n"),
        ]
    )

    make_publisher(runner).preflight()

    assert [command for command, _ in runner.calls] == expected_commands()
    assert [cwd for _, cwd in runner.calls] == [REPOSITORY_ROOT] * 5


@pytest.mark.parametrize(
    ("responses", "expected_call_count"),
    [
        ([result("C:/another/repository\n")], 1),
        ([result(str(REPOSITORY_ROOT)), result("feature/publish\n")], 2),
        (
            [
                result(str(REPOSITORY_ROOT)),
                result("master\n"),
                result(" M tracked-file.py\n"),
            ],
            3,
        ),
        (
            [
                result(str(REPOSITORY_ROOT)),
                result("master\n"),
                result(),
                result(),
                result("1\t0\n"),
            ],
            5,
        ),
    ],
    ids=["wrong-root", "wrong-branch", "dirty-tracked-files", "remote-diverged"],
)
def test_preflight_stops_at_the_first_invalid_git_state(
    responses: list[CommandResult], expected_call_count: int
) -> None:
    runner = RecordingRunner(responses)

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).preflight()

    assert raised.value.stage == "preflight"
    assert len(runner.calls) == expected_call_count
    assert [command for command, _ in runner.calls] == expected_commands()[:expected_call_count]


def test_preflight_maps_git_command_failures_to_sanitized_error() -> None:
    runner = RecordingRunner([result(returncode=128, stderr="fatal: unsafe details\nnext line")])

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).preflight()

    assert raised.value.stage == "preflight"
    assert raised.value.message == "git command failed"


def test_preflight_does_not_leak_credentials_from_git_stderr() -> None:
    leaked_token = "ghp_superSecretToken123"
    leaked_url = f"https://oauth2:{leaked_token}@github.com/yamopeng0918/AI-Summary.git"
    runner = RecordingRunner([result(returncode=128, stderr=f"fatal: could not read from {leaked_url}\n")])

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).preflight()

    assert raised.value.stage == "preflight"
    assert raised.value.message == "git command failed"
    assert leaked_token not in raised.value.message
    assert leaked_url not in raised.value.message


def test_run_gates_runs_all_local_checks_in_order() -> None:
    runner = RecordingRunner([result(), result(), result(), result()])

    make_publisher(runner).run_gates()

    assert [command for command, _ in runner.calls] == expected_gate_commands()
    assert [cwd for _, cwd in runner.calls] == [
        REPOSITORY_ROOT,
        REPOSITORY_ROOT / "site",
        REPOSITORY_ROOT / "site",
        REPOSITORY_ROOT,
    ]


@pytest.mark.parametrize("failed_index", range(4))
def test_run_gates_stops_at_first_failed_check(failed_index: int) -> None:
    runner = RecordingRunner(
        [
            result(returncode=1) if index == failed_index else result()
            for index in range(failed_index + 1)
        ]
    )

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).run_gates()

    assert raised.value.stage == "deploy"
    assert len(runner.calls) == failed_index + 1
    assert [command for command, _ in runner.calls] == expected_gate_commands()[: failed_index + 1]


def test_commit_and_push_stages_only_one_utf8_summary_and_returns_head_sha() -> None:
    record = make_record("摘要")
    path = SUMMARY_ROOT / "摘要.json"
    relative_path = "data/summaries/摘要.json"
    commit_sha = "a" * 40
    runner = RecordingRunner(
        [
            result(returncode=1),
            result(),
            result(relative_path.encode("utf-8") + b"\0"),
            result(),
            result(f"{commit_sha}\n"),
            result(),
        ]
    )

    returned_sha = make_publisher(runner).commit_and_push(record, path)

    assert returned_sha == commit_sha
    assert [command for command, _ in runner.calls] == [
        ["git", "cat-file", "-e", f"HEAD:{relative_path}"],
        ["git", "add", "--", relative_path],
        ["git", "diff", "--cached", "--name-only", "-z"],
        ["git", "commit", "-m", "content: publish 摘要"],
        ["git", "rev-parse", "HEAD"],
        ["git", "push", "origin", "master"],
    ]
    assert [cwd for _, cwd in runner.calls] == [REPOSITORY_ROOT] * 6


def test_commit_and_push_reuses_head_file_without_empty_commit() -> None:
    record = make_record("existing")
    path = SUMMARY_ROOT / "existing.json"
    relative_path = "data/summaries/existing.json"
    file_commit = "b" * 40
    runner = RecordingRunner([result(), result(f"{file_commit}\n"), result()])

    returned_sha = make_publisher(runner).commit_and_push(record, path)

    assert returned_sha == file_commit
    assert [command for command, _ in runner.calls] == [
        ["git", "cat-file", "-e", f"HEAD:{relative_path}"],
        ["git", "log", "-1", "--format=%H", "--", relative_path],
        ["git", "push", "origin", "master"],
    ]
    assert [cwd for _, cwd in runner.calls] == [REPOSITORY_ROOT] * 3


def test_commit_and_push_rejects_extra_staged_paths() -> None:
    record = make_record("example")
    path = SUMMARY_ROOT / "example.json"
    runner = RecordingRunner(
        [
            result(returncode=1),
            result(),
            result(b"data/summaries/example.json\0README.md\0"),
        ]
    )

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).commit_and_push(record, path)

    assert raised.value.stage == "deploy"
    assert [command for command, _ in runner.calls] == [
        ["git", "cat-file", "-e", "HEAD:data/summaries/example.json"],
        ["git", "add", "--", "data/summaries/example.json"],
        ["git", "diff", "--cached", "--name-only", "-z"],
    ]


def test_commit_and_push_rejects_a_mismatched_summary_filename_before_git() -> None:
    record = make_record("example")
    path = SUMMARY_ROOT / "different.json"
    runner = RecordingRunner([])

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).commit_and_push(record, path)

    assert raised.value.stage == "deploy"
    assert raised.value.message == "summary file path does not match record id"
    assert runner.calls == []


def test_commit_and_push_rejects_an_in_repo_non_summary_path_before_git() -> None:
    record = make_record("example")
    path = REPOSITORY_ROOT / "README.md"
    runner = RecordingRunner([])

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).commit_and_push(record, path)

    assert raised.value.stage == "deploy"
    assert raised.value.message == "summary file path does not match record id"
    assert runner.calls == []


def test_wait_for_workflow_ignores_other_commits_and_workflows_until_matching_success() -> None:
    commit_sha = "a" * 40
    workflow_url = "https://github.com/yamopeng0918/AI-Summary/actions/runs/42"
    api_url = (
        "https://api.github.com/repos/yamopeng0918/AI-Summary/actions/runs"
        f"?head_sha={commit_sha}&per_page=20"
    )
    responses = [
        {
            "workflow_runs": [
                {
                    "head_sha": "b" * 40,
                    "name": "Deploy to GitHub Pages",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/yamopeng0918/AI-Summary/actions/runs/11",
                }
            ]
        },
        {
            "workflow_runs": [
                {
                    "head_sha": commit_sha,
                    "name": "Different Workflow",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/yamopeng0918/AI-Summary/actions/runs/12",
                }
            ]
        },
        {
            "workflow_runs": [
                {
                    "head_sha": commit_sha,
                    "name": "Deploy to GitHub Pages",
                    "status": "queued",
                    "conclusion": None,
                    "html_url": workflow_url,
                }
            ]
        },
        {
            "workflow_runs": [
                {
                    "head_sha": commit_sha,
                    "name": "Deploy to GitHub Pages",
                    "status": "in_progress",
                    "conclusion": None,
                    "html_url": workflow_url,
                }
            ]
        },
        {
            "workflow_runs": [
                {
                    "head_sha": commit_sha,
                    "name": "Deploy to GitHub Pages",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": workflow_url,
                }
            ]
        },
    ]
    seen_urls: list[str] = []
    sleeps: list[float] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        seen_urls.append(url)
        return responses.pop(0)

    workflow_run_url = make_publisher(
        RecordingRunner([]),
        fetch_json=fake_fetch_json,
        sleep=lambda seconds: sleeps.append(seconds),
        poll_attempts=5,
        poll_delay_seconds=7,
    ).wait_for_workflow(commit_sha)

    assert workflow_run_url == workflow_url
    assert seen_urls == [api_url] * 5
    assert sleeps == [7, 7, 7, 7]


def test_wait_for_workflow_raises_for_a_failed_matching_run_without_sleeping() -> None:
    commit_sha = "a" * 40
    publisher = make_publisher(
        RecordingRunner([]),
        fetch_json=lambda _url: {
            "workflow_runs": [
                {
                    "head_sha": commit_sha,
                    "name": "Deploy to GitHub Pages",
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/yamopeng0918/AI-Summary/actions/runs/99",
                }
            ]
        },
        sleep=lambda _seconds: pytest.fail("wait_for_workflow should not sleep after completion"),
    )

    with pytest.raises(PublishError) as raised:
        publisher.wait_for_workflow(commit_sha)

    assert raised.value.stage == "workflow"
    assert raised.value.message == "workflow run failed"


def test_wait_for_workflow_times_out_after_bounded_incomplete_attempts() -> None:
    commit_sha = "a" * 40
    sleeps: list[float] = []
    seen_urls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        seen_urls.append(url)
        return {"workflow_runs": []}

    publisher = make_publisher(
        RecordingRunner([]),
        fetch_json=fake_fetch_json,
        sleep=lambda seconds: sleeps.append(seconds),
        poll_attempts=3,
        poll_delay_seconds=5,
    )

    with pytest.raises(PublishError) as raised:
        publisher.wait_for_workflow(commit_sha)

    assert raised.value.stage == "workflow"
    assert raised.value.message == "workflow run did not complete in time"
    assert len(seen_urls) == 3
    assert sleeps == [5, 5]


def test_verify_public_uses_cache_busted_homepage_and_quoted_detail_route() -> None:
    record_id = "中文 摘要?#"
    homepage_url = "https://yamopeng0918.github.io/AI-Summary/?verify=1723600000"
    detail_url = (
        "https://yamopeng0918.github.io/AI-Summary/summaries/"
        f"{quote(record_id, safe='')}/"
    )
    seen_urls: list[str] = []

    def fake_fetch_text(url: str) -> tuple[int, str]:
        seen_urls.append(url)
        if url == homepage_url:
            return 200, f"<a>{record_id}</a>"
        if url == detail_url:
            return 200, "<h1>detail</h1>"
        raise AssertionError(url)

    make_publisher(
        RecordingRunner([]),
        fetch_text=fake_fetch_text,
        now=lambda: 1723600000,
    ).verify_public(record_id)

    assert seen_urls == [homepage_url, detail_url]


@pytest.mark.parametrize(
    ("fetch_text", "expected_message"),
    [
        (
            lambda _url: (503, "down"),
            "public page request failed",
        ),
        (
            lambda _url: (_ for _ in ()).throw(RuntimeError("boom")),
            "public page request failed",
        ),
    ],
    ids=["non-200", "fetch-error"],
)
def test_verify_public_maps_request_problems_to_safe_public_errors(fetch_text, expected_message) -> None:
    publisher = make_publisher(
        RecordingRunner([]),
        fetch_text=fetch_text,
        now=lambda: 1,
    )

    with pytest.raises(PublishError) as raised:
        publisher.verify_public("example")

    assert raised.value.stage == "public"
    assert raised.value.message == expected_message


def test_verify_public_rejects_homepages_missing_the_exact_record_id() -> None:
    publisher = make_publisher(
        RecordingRunner([]),
        fetch_text=lambda _url: (200, "<a>something-else</a>"),
        now=lambda: 1,
    )

    with pytest.raises(PublishError) as raised:
        publisher.verify_public("example")

    assert raised.value.stage == "public"
    assert raised.value.message == "published summary is not visible on the homepage"


def test_publish_orchestrates_a_new_summary_successfully(tmp_path) -> None:
    record = make_record("fresh", canonicalUrl="https://example.com/article")
    calls: list[object] = []

    def add_summary(raw_url: str) -> SummaryRecord:
        calls.append(("add_summary", raw_url))
        return record

    publisher = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([]),
        add_summary=add_summary,
        summary_root=tmp_path,
    )
    publisher.preflight = lambda: calls.append("preflight")
    publisher.run_gates = lambda: calls.append("run_gates")
    publisher.commit_and_push = lambda current_record, path: calls.append(
        ("commit_and_push", current_record.id, path)
    ) or ("c" * 40)
    publisher.wait_for_workflow = lambda commit_sha: calls.append(
        ("wait_for_workflow", commit_sha)
    ) or "https://github.com/yamopeng0918/AI-Summary/actions/runs/77"
    publisher.verify_public = lambda record_id: calls.append(("verify_public", record_id))

    result = publisher.publish("https://example.com/article?utm_source=newsletter")

    assert result == PublishResult(
        record_id="fresh",
        commit_sha="c" * 40,
        workflow_url="https://github.com/yamopeng0918/AI-Summary/actions/runs/77",
        detail_url="https://yamopeng0918.github.io/AI-Summary/summaries/fresh/",
    )
    assert calls == [
        "preflight",
        ("add_summary", "https://example.com/article?utm_source=newsletter"),
        "run_gates",
        ("commit_and_push", "fresh", tmp_path / "fresh.json"),
        ("wait_for_workflow", "c" * 40),
        ("verify_public", "fresh"),
    ]


def test_publish_reuses_retained_json_without_calling_the_provider(tmp_path) -> None:
    record = make_record("existing", canonicalUrl="https://example.com/article")
    existing_path = tmp_path / "existing.json"
    existing_path.write_text(record.model_dump_json(by_alias=True), encoding="utf-8")
    add_calls: list[str] = []
    calls: list[object] = []

    publisher = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([record]),
        add_summary=lambda raw_url: add_calls.append(raw_url) or make_record("unexpected"),
        summary_root=tmp_path,
    )
    publisher.preflight = lambda: calls.append("preflight")
    publisher.run_gates = lambda: calls.append("run_gates")
    publisher.commit_and_push = lambda current_record, path: calls.append(
        ("commit_and_push", current_record.id, path)
    ) or ("d" * 40)
    publisher.wait_for_workflow = lambda commit_sha: calls.append(
        ("wait_for_workflow", commit_sha)
    ) or "https://github.com/yamopeng0918/AI-Summary/actions/runs/88"
    publisher.verify_public = lambda record_id: calls.append(("verify_public", record_id))

    result = publisher.publish("https://example.com/article?utm_source=newsletter")

    assert result.record_id == "existing"
    assert result.commit_sha == "d" * 40
    assert add_calls == []
    assert calls == [
        "preflight",
        "run_gates",
        ("commit_and_push", "existing", existing_path),
        ("wait_for_workflow", "d" * 40),
        ("verify_public", "existing"),
    ]


def test_publish_supports_an_already_pushed_resume_without_calling_the_provider(tmp_path) -> None:
    record = make_record("existing", canonicalUrl="https://example.com/article")
    existing_path = tmp_path / "existing.json"
    existing_path.write_text(record.model_dump_json(by_alias=True), encoding="utf-8")
    add_calls: list[str] = []
    calls: list[object] = []

    publisher = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([record]),
        add_summary=lambda raw_url: add_calls.append(raw_url) or make_record("unexpected"),
        summary_root=tmp_path,
    )
    publisher.preflight = lambda: calls.append("preflight")
    publisher.run_gates = lambda: calls.append("run_gates")
    publisher.commit_and_push = lambda current_record, path: calls.append(
        ("commit_and_push", current_record.id, path)
    ) or ("e" * 40)
    publisher.wait_for_workflow = lambda commit_sha: calls.append(
        ("wait_for_workflow", commit_sha)
    ) or "https://github.com/yamopeng0918/AI-Summary/actions/runs/89"
    publisher.verify_public = lambda record_id: calls.append(("verify_public", record_id))

    result = publisher.publish("https://example.com/article")

    assert result.workflow_url.endswith("/89")
    assert add_calls == []
    assert calls == [
        "preflight",
        "run_gates",
        ("commit_and_push", "existing", existing_path),
        ("wait_for_workflow", "e" * 40),
        ("verify_public", "existing"),
    ]


@pytest.mark.parametrize(
    ("failing_step", "expected_calls"),
    [
        (
            "run_gates",
            ["preflight", ("add_summary", "https://example.com/article"), "run_gates"],
        ),
        (
            "commit_and_push",
            [
                "preflight",
                ("add_summary", "https://example.com/article"),
                "run_gates",
                ("commit_and_push", "fresh"),
            ],
        ),
        (
            "wait_for_workflow",
            [
                "preflight",
                ("add_summary", "https://example.com/article"),
                "run_gates",
                ("commit_and_push", "fresh"),
                ("wait_for_workflow", "f" * 40),
            ],
        ),
        (
            "verify_public",
            [
                "preflight",
                ("add_summary", "https://example.com/article"),
                "run_gates",
                ("commit_and_push", "fresh"),
                ("wait_for_workflow", "f" * 40),
                ("verify_public", "fresh"),
            ],
        ),
    ],
)
def test_publish_stops_after_the_first_failing_stage(
    tmp_path, failing_step: str, expected_calls: list[object]
) -> None:
    record = make_record("fresh", canonicalUrl="https://example.com/article")
    calls: list[object] = []

    def add_summary(raw_url: str) -> SummaryRecord:
        calls.append(("add_summary", raw_url))
        return record

    publisher = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([]),
        add_summary=add_summary,
        summary_root=tmp_path,
    )
    publisher.preflight = lambda: calls.append("preflight")

    def fail(stage: str) -> None:
        raise PublishError(stage, f"{stage} failed")

    publisher.run_gates = (
        (lambda: calls.append("run_gates") or fail("deploy"))
        if failing_step == "run_gates"
        else (lambda: calls.append("run_gates"))
    )
    publisher.commit_and_push = (
        (lambda current_record, _path: calls.append(("commit_and_push", current_record.id)) or fail("deploy"))
        if failing_step == "commit_and_push"
        else (lambda current_record, _path: calls.append(("commit_and_push", current_record.id)) or ("f" * 40))
    )
    publisher.wait_for_workflow = (
        (lambda commit_sha: calls.append(("wait_for_workflow", commit_sha)) or fail("workflow"))
        if failing_step == "wait_for_workflow"
        else (lambda commit_sha: calls.append(("wait_for_workflow", commit_sha)) or "https://github.com/yamopeng0918/AI-Summary/actions/runs/90")
    )
    publisher.verify_public = (
        (lambda record_id: calls.append(("verify_public", record_id)) or fail("public"))
        if failing_step == "verify_public"
        else (lambda record_id: calls.append(("verify_public", record_id)))
    )

    with pytest.raises(PublishError):
        publisher.publish("https://example.com/article")

    assert calls == expected_calls


def test_resolve_summary_creates_a_new_summary_when_no_canonical_match_exists(tmp_path) -> None:
    created = make_record("created", canonicalUrl="https://example.com/article")
    add_calls: list[str] = []

    record, path, created_new = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([]),
        add_summary=lambda raw_url: add_calls.append(raw_url) or created,
        summary_root=tmp_path,
    ).resolve_summary("https://example.com/article?utm_source=newsletter")

    assert record == created
    assert path == tmp_path / "created.json"
    assert created_new is True
    assert add_calls == ["https://example.com/article?utm_source=newsletter"]


def test_resolve_summary_reuses_an_existing_canonical_match_without_calling_provider(tmp_path) -> None:
    existing = make_record("existing", canonicalUrl="https://example.com/article")
    existing_path = tmp_path / "existing.json"
    existing_path.write_text(existing.model_dump_json(by_alias=True), encoding="utf-8")
    add_calls: list[str] = []

    record, path, created_new = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([existing]),
        add_summary=lambda raw_url: add_calls.append(raw_url) or make_record("unexpected"),
        summary_root=tmp_path,
    ).resolve_summary("https://example.com/article?utm_source=newsletter")

    assert record == existing
    assert path == existing_path
    assert created_new is False
    assert add_calls == []


def test_resolve_summary_rejects_multiple_existing_canonical_matches(tmp_path) -> None:
    first = make_record("first", canonicalUrl="https://example.com/article")
    second = make_record("second", canonicalUrl="https://example.com/article")

    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([first, second]),
            summary_root=tmp_path,
        ).resolve_summary("https://example.com/article")

    assert raised.value.stage == "summary"
    assert raised.value.message == "multiple summaries already exist for this URL"


def test_resolve_summary_rejects_a_retained_match_when_its_file_is_missing(tmp_path) -> None:
    existing = make_record("existing", canonicalUrl="https://example.com/article")

    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([existing]),
            summary_root=tmp_path,
        ).resolve_summary("https://example.com/article")

    assert raised.value.stage == "summary"
    assert raised.value.message == "stored summary file is missing"


def test_resolve_summary_maps_invalid_public_urls_to_a_safe_publishing_error(tmp_path) -> None:
    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([]),
            summary_root=tmp_path,
        ).resolve_summary("file:///private")

    assert raised.value.stage == "summary"
    assert raised.value.message == "URL must be a public HTTP(S) URL"


def test_resolve_summary_rejects_new_records_whose_ids_hide_traversal_segments(tmp_path) -> None:
    created = make_record("nested/../escape", canonicalUrl="https://example.com/article")

    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([]),
            add_summary=lambda _raw_url: created,
            summary_root=tmp_path,
        ).resolve_summary("https://example.com/article")

    assert raised.value.stage == "summary"
    assert raised.value.message == "summary file path is invalid"
