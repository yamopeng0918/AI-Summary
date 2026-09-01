from pathlib import Path

import pytest

from ai_digest.domain import DigestError
from ai_digest.site_build import CommandResult, SiteBuildService


ROOT = Path("C:/workspace/AI-Summary")


class RecordingRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> CommandResult:
        self.calls.append((list(command), cwd))
        return self.responses.pop(0)


def make_service(
    runner: RecordingRunner,
    *,
    platform: str = "win32",
    on_progress=lambda _step: None,
) -> SiteBuildService:
    return SiteBuildService(
        repository_root=ROOT,
        run_command=runner,
        platform=platform,
        python_executable="C:/Python/python.exe",
        on_progress=on_progress,
    )


def test_build_runs_pages_build_then_complete_verifier_on_windows() -> None:
    runner = RecordingRunner([CommandResult(0), CommandResult(0)])
    stages: list[str] = []

    path = make_service(runner, on_progress=stages.append).run()

    assert runner.calls == [
        (["npm.cmd", "run", "build:pages"], ROOT / "site"),
        (
            [
                "C:/Python/python.exe",
                "scripts/verify_deployment.py",
                "--tracked",
                "--dist",
                "site/dist",
                "--base",
                "/AI-Summary/",
            ],
            ROOT,
        ),
    ]
    assert stages == ["build", "verify"]
    assert path == (ROOT / "site" / "dist").resolve()


def test_build_uses_npm_outside_windows() -> None:
    runner = RecordingRunner([CommandResult(0), CommandResult(0)])

    make_service(runner, platform="linux").run()

    assert runner.calls[0][0] == ["npm", "run", "build:pages"]


def test_build_failure_stops_before_verifier_and_sanitizes_details() -> None:
    runner = RecordingRunner(
        [CommandResult(2, stdout="provider-key", stderr="C:/private/path")]
    )

    with pytest.raises(DigestError) as raised:
        make_service(runner).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "SITE_BUILD_FAILED",
        "message": "site build command failed",
        "retryable": False,
    }
    assert len(runner.calls) == 1
    assert "provider-key" not in str(raised.value.as_dict())
    assert "C:/private/path" not in str(raised.value.as_dict())


def test_verifier_failure_has_distinct_safe_message() -> None:
    runner = RecordingRunner([CommandResult(0), CommandResult(3, stderr="secret")])

    with pytest.raises(DigestError) as raised:
        make_service(runner).run()

    assert raised.value.as_dict() == {
        "stage": "deploy",
        "code": "SITE_BUILD_FAILED",
        "message": "site verification failed",
        "retryable": False,
    }
    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    ("failure_call", "expected_message"),
    [(1, "site build command failed"), (2, "site verification failed")],
)
def test_command_start_failure_is_sanitized(
    failure_call: int, expected_message: str
) -> None:
    calls = 0

    def failing_runner(command: list[str], cwd: Path) -> CommandResult:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError("C:/private/path provider-key")
        return CommandResult(0)

    service = SiteBuildService(
        ROOT,
        failing_runner,
        "win32",
        "C:/Python/python.exe",
        lambda _step: None,
    )

    with pytest.raises(DigestError) as raised:
        service.run()

    assert raised.value.message == expected_message
    assert "private" not in str(raised.value.as_dict())
    assert "provider-key" not in str(raised.value.as_dict())
