from pathlib import Path
import sys

import pytest

from ai_digest.deployment import DeployService
from ai_digest.domain import DigestError
from ai_digest.site_build import CommandResult


ROOT = Path("C:/workspace/AI-Summary")
HEAD = "a" * 40


class FakeBuildService:
    def __init__(
        self,
        events: list[str] | None = None,
        error: DigestError | None = None,
    ) -> None:
        self.calls = 0
        self.events = events
        self.error = error

    def run(self) -> Path:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.events is not None:
            self.events.append("build-complete")
        return (ROOT / "site" / "dist").resolve()


class RecordingRunner:
    def __init__(
        self, responses: list[CommandResult], events: list[str] | None = None
    ) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], Path]] = []
        self.events = events

    def __call__(self, command, cwd: Path) -> CommandResult:
        self.calls.append((list(command), cwd))
        if self.events is not None:
            self.events.append(" ".join(command))
        return self.responses.pop(0)


class SequenceFetcher:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def __call__(self, url: str) -> object:
        self.urls.append(url)
        value = self.payloads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def workflow(
    status: str, conclusion=None, *, sha: str = HEAD
) -> dict[str, object]:
    return {
        "head_sha": sha,
        "name": "Deploy to GitHub Pages",
        "status": status,
        "conclusion": conclusion,
        "html_url": "https://github.example/run/1",
    }


def make_service(
    runner: RecordingRunner,
    *,
    build: FakeBuildService | None = None,
    fetch_json=None,
    sleep=None,
    poll_attempts: int = 30,
    poll_delay_seconds: float = 10,
) -> DeployService:
    return DeployService(
        ROOT,
        build or FakeBuildService(),
        runner,
        fetch_json=fetch_json or (lambda _url: {"workflow_runs": [workflow("completed", "success")]}),
        sleep=sleep or (lambda _seconds: None),
        on_progress=lambda _step, _status=None: None,
        poll_attempts=poll_attempts,
        poll_delay_seconds=poll_delay_seconds,
    )


def runner_for_success(
    counts: str = "0\t0\n",
    *,
    include_push: bool = False,
    events: list[str] | None = None,
    smoke: CommandResult | None = None,
) -> RecordingRunner:
    responses = [
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="master\n"),
        CommandResult(0, stdout=""),
        CommandResult(0),
        CommandResult(0, stdout=counts),
    ]
    if include_push:
        responses.append(CommandResult(0))
    responses.extend([
        CommandResult(0, stdout=f"{HEAD}\n"),
        smoke or CommandResult(0),
    ])
    return RecordingRunner(responses, events)


def test_synchronized_master_builds_without_push() -> None:
    runner = RecordingRunner([
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="master\n"),
        CommandResult(0, stdout=""),
        CommandResult(0),
        CommandResult(0, stdout="0\t0\n"),
        CommandResult(0, stdout=f"{HEAD}\n"),
        CommandResult(0),
    ])
    build = FakeBuildService()
    stages: list[tuple[str, str | None]] = []
    service = DeployService(
        ROOT,
        build,
        runner,
        fetch_json=lambda _url: {
            "workflow_runs": [{
                "head_sha": HEAD,
                "name": "Deploy to GitHub Pages",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.example/run/1",
            }]
        },
        sleep=lambda _seconds: None,
        on_progress=lambda step, status=None: stages.append((step, status)),
    )

    result = service.run()

    assert build.calls == 1
    assert not any(call[0][:2] == ["git", "push"] for call in runner.calls)
    assert result.push_status == "unchanged"
    assert result.commit_sha == HEAD
    assert stages[:4] == [
        ("preflight", None),
        ("push", "unchanged"),
        ("workflow", None),
        ("public", None),
    ]


@pytest.mark.parametrize("counts", ["0\t1\n", "2\t1\n"])
def test_remote_only_commits_fail_before_build(counts: str) -> None:
    runner = RecordingRunner([
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="master\n"),
        CommandResult(0, stdout=""),
        CommandResult(0),
        CommandResult(0, stdout=counts),
    ])
    build = FakeBuildService()
    service = make_service(runner, build=build)

    with pytest.raises(DigestError) as raised:
        service.run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PREFLIGHT_FAILED",
        "message": "deployment preflight failed",
        "retryable": False,
    }
    assert build.calls == 0


def test_local_ahead_builds_then_pushes_all_commits() -> None:
    events: list[str] = []
    runner = runner_for_success(counts="2\t0\n", include_push=True, events=events)
    build = FakeBuildService(events)
    service = make_service(runner, build=build)

    result = service.run()

    assert build.calls == 1
    assert (["git", "push", "origin", "master"], ROOT) in runner.calls
    assert events.index("build-complete") < events.index("git push origin master")
    assert result.push_status == "pushed"


def test_tracked_status_rejects_before_fetch_or_build() -> None:
    runner = RecordingRunner([
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="master\n"),
        CommandResult(0, stdout=" M progress.md\n"),
    ])
    build = FakeBuildService()

    with pytest.raises(DigestError):
        make_service(runner, build=build).run()

    assert build.calls == 0
    assert not any(call[0][1] == "fetch" for call in runner.calls)


def test_preflight_ignores_untracked_files() -> None:
    runner = runner_for_success(counts="0\t0\n")

    result = make_service(runner).run()

    assert result.push_status == "unchanged"
    assert ("git", "status", "--porcelain", "--untracked-files=no") in [
        tuple(command) for command, _cwd in runner.calls
    ]


def test_preflight_oserror_is_sanitized() -> None:
    marker = "private-command-output"

    def raises_oserror(_command, _cwd: Path) -> CommandResult:
        raise OSError(marker)

    service = DeployService(
        ROOT,
        FakeBuildService(),
        raises_oserror,
        fetch_json=lambda _url: {},
        sleep=lambda _seconds: None,
        on_progress=lambda _step, _status=None: None,
    )

    with pytest.raises(DigestError) as raised:
        service.run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PREFLIGHT_FAILED",
        "message": "deployment preflight failed",
        "retryable": False,
    }
    assert marker not in str(raised.value)


def test_preflight_nonzero_result_is_sanitized() -> None:
    marker = "private-command-output"
    runner = RecordingRunner([CommandResult(1, stderr=marker)])

    with pytest.raises(DigestError) as raised:
        make_service(runner).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PREFLIGHT_FAILED",
        "message": "deployment preflight failed",
        "retryable": False,
    }
    assert marker not in str(raised.value)


def test_push_nonzero_result_is_sanitized_after_build() -> None:
    marker = "private-command-output"
    runner = runner_for_success(counts="1\t0\n", include_push=True)
    runner.responses[5] = CommandResult(1, stderr=marker)
    build = FakeBuildService()
    fetcher = SequenceFetcher([
        {"workflow_runs": [workflow("completed", "success")]}
    ])

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build, fetch_json=fetcher).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PUSH_FAILED",
        "message": "deployment push failed",
        "retryable": False,
    }
    assert build.calls == 1
    assert fetcher.urls == []
    assert marker not in str(raised.value)


def test_build_failure_stops_before_push() -> None:
    runner = runner_for_success(counts="1\t0\n", include_push=True)
    build = FakeBuildService(
        error=DigestError(
            "deploy", "SITE_BUILD_FAILED", "site build command failed", False
        )
    )

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build).run()

    assert raised.value.code == "SITE_BUILD_FAILED"
    assert build.calls == 1
    assert not any(
        command == ["git", "push", "origin", "master"]
        for command, _cwd in runner.calls
    )


def test_non_root_repository_fails_before_branch_or_build() -> None:
    runner = RecordingRunner([CommandResult(0, stdout="C:/workspace/other")])
    build = FakeBuildService()

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PREFLIGHT_FAILED",
        "message": "deployment preflight failed",
        "retryable": False,
    }
    assert build.calls == 0
    assert runner.calls == [
        (["git", "rev-parse", "--show-toplevel"], ROOT)
    ]


def test_non_master_branch_fails_before_status_or_build() -> None:
    runner = RecordingRunner([
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="feature/deploy-cli\n"),
    ])
    build = FakeBuildService()

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build).run()

    assert raised.value.code == "DEPLOY_PREFLIGHT_FAILED"
    assert build.calls == 0
    assert [command for command, _cwd in runner.calls] == [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "branch", "--show-current"],
    ]


@pytest.mark.parametrize(
    "counts",
    ["", "1\n", "1\t0\textra\n", "local\t0\n", "-1\t0\n"],
)
def test_malformed_or_invalid_revision_counts_fail_before_build(counts: str) -> None:
    runner = RecordingRunner([
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="master\n"),
        CommandResult(0, stdout=""),
        CommandResult(0),
        CommandResult(0, stdout=counts),
    ])
    build = FakeBuildService()

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build).run()

    assert raised.value.code == "DEPLOY_PREFLIGHT_FAILED"
    assert build.calls == 0


def test_fetch_failure_stops_before_revision_check_and_build() -> None:
    marker = "private-fetch-output"
    runner = RecordingRunner([
        CommandResult(0, stdout=str(ROOT)),
        CommandResult(0, stdout="master\n"),
        CommandResult(0, stdout=""),
        CommandResult(1, stderr=marker),
    ])
    build = FakeBuildService()

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PUSH_FAILED",
        "message": "deployment fetch failed",
        "retryable": False,
    }
    assert build.calls == 0
    assert marker not in str(raised.value.as_dict())


def test_workflow_in_progress_is_polled_until_success() -> None:
    fetcher = SequenceFetcher([
        {"workflow_runs": [workflow("in_progress")]},
        {"workflow_runs": [workflow("completed", "success")]},
    ])
    sleeps: list[float] = []
    service = make_service(
        runner_for_success(),
        fetch_json=fetcher,
        sleep=sleeps.append,
        poll_attempts=2,
        poll_delay_seconds=0.25,
    )

    result = service.run()

    assert result.workflow_url == "https://github.example/run/1"
    assert sleeps == [0.25]
    assert all(f"head_sha={HEAD}" in url for url in fetcher.urls)


def test_queued_workflow_is_polled_until_success() -> None:
    fetcher = SequenceFetcher([
        {"workflow_runs": [workflow("queued")]},
        {"workflow_runs": [workflow("completed", "success")]},
    ])
    sleeps: list[float] = []

    result = make_service(
        runner_for_success(),
        fetch_json=fetcher,
        sleep=sleeps.append,
        poll_attempts=2,
        poll_delay_seconds=0.25,
    ).run()

    assert result.workflow_url == "https://github.example/run/1"
    assert sleeps == [0.25]
    assert len(fetcher.urls) == 2


def test_workflow_ignores_nonmatching_runs_until_exact_match() -> None:
    wrong_sha = workflow("completed", "success", sha="b" * 40)
    wrong_name = workflow("completed", "success")
    wrong_name["name"] = "Other workflow"
    fetcher = SequenceFetcher([
        {"workflow_runs": [wrong_sha]},
        {"workflow_runs": [wrong_name]},
        {"workflow_runs": [workflow("completed", "success")]},
    ])
    sleeps: list[float] = []
    service = make_service(
        runner_for_success(),
        fetch_json=fetcher,
        sleep=sleeps.append,
        poll_attempts=3,
        poll_delay_seconds=0.25,
    )

    result = service.run()

    assert result.workflow_url == "https://github.example/run/1"
    assert sleeps == [0.25, 0.25]


def test_workflow_failure_does_not_run_public_smoke() -> None:
    runner = runner_for_success()
    service = make_service(
        runner,
        fetch_json=SequenceFetcher([
            {"workflow_runs": [workflow("completed", "failure")]}
        ]),
        poll_attempts=1,
    )

    with pytest.raises(DigestError):
        service.run()

    assert not any(
        command == [sys.executable, "scripts/smoke_pages.py"]
        for command, _cwd in runner.calls
    )


def test_cancelled_workflow_fails_without_running_public_smoke() -> None:
    runner = runner_for_success()

    with pytest.raises(DigestError) as raised:
        make_service(
            runner,
            fetch_json=SequenceFetcher([
                {"workflow_runs": [workflow("completed", "cancelled")]}
            ]),
            poll_attempts=1,
        ).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_WORKFLOW_FAILED",
        "message": "deployment workflow failed",
        "retryable": False,
    }
    assert not any(
        command == [sys.executable, "scripts/smoke_pages.py"]
        for command, _cwd in runner.calls
    )


@pytest.mark.parametrize(
    ("payloads", "retryable"),
    [
        ([{"workflow_runs": [workflow("completed", "failure")]}], False),
        ([OSError("PRIVATE HTTP BODY")], True),
        ([{"workflow_runs": []}], True),
    ],
)
def test_workflow_failures_are_safe(payloads, retryable: bool) -> None:
    service = make_service(
        runner_for_success(), fetch_json=SequenceFetcher(payloads), poll_attempts=1
    )

    with pytest.raises(DigestError) as raised:
        service.run()

    assert raised.value.code == "DEPLOY_WORKFLOW_FAILED"
    assert raised.value.retryable is retryable
    assert "PRIVATE HTTP BODY" not in str(raised.value.as_dict())


def test_public_smoke_failure_is_retryable_and_safe() -> None:
    runner = runner_for_success(smoke=CommandResult(3, stderr="SECRET BODY"))

    with pytest.raises(DigestError) as raised:
        make_service(runner).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PUBLIC_FAILED",
        "message": "public deployment verification failed",
        "retryable": True,
    }


def test_public_smoke_oserror_is_retryable_and_safe() -> None:
    runner = runner_for_success()

    def raises_for_smoke(command, cwd: Path) -> CommandResult:
        if command == [sys.executable, "scripts/smoke_pages.py"]:
            raise OSError("SECRET BODY")
        return runner(command, cwd)

    with pytest.raises(DigestError) as raised:
        make_service(raises_for_smoke).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PUBLIC_FAILED",
        "message": "public deployment verification failed",
        "retryable": True,
    }
    assert "SECRET BODY" not in str(raised.value.as_dict())
