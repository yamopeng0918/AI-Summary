from pathlib import Path

import pytest

from ai_digest.deployment import DeployService
from ai_digest.domain import DigestError
from ai_digest.site_build import CommandResult


ROOT = Path("C:/workspace/AI-Summary")
HEAD = "a" * 40


class FakeBuildService:
    def __init__(self) -> None:
        self.calls = 0

    def run(self) -> Path:
        self.calls += 1
        return (ROOT / "site" / "dist").resolve()


class RecordingRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command, cwd: Path) -> CommandResult:
        self.calls.append((list(command), cwd))
        return self.responses.pop(0)


def make_service(
    runner: RecordingRunner,
    *,
    build: FakeBuildService | None = None,
) -> DeployService:
    return DeployService(
        ROOT,
        build or FakeBuildService(),
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
        on_progress=lambda _step, _status=None: None,
    )


def runner_for_success(counts: str, *, include_push: bool = False) -> RecordingRunner:
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
        CommandResult(0),
    ])
    return RecordingRunner(responses)


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
    runner = runner_for_success(counts="2\t0\n", include_push=True)
    build = FakeBuildService()
    service = make_service(runner, build=build)

    result = service.run()

    assert build.calls == 1
    assert (["git", "push", "origin", "master"], ROOT) in runner.calls
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

    with pytest.raises(DigestError) as raised:
        make_service(runner, build=build).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "DEPLOY_PUSH_FAILED",
        "message": "deployment push failed",
        "retryable": False,
    }
    assert build.calls == 1
    assert marker not in str(raised.value)
