from pathlib import Path

import pytest

from ai_digest.publishing import CommandResult, PublishError, PublishingConfig, SummaryPublisher


REPOSITORY_ROOT = Path("C:/workspace/AI-Summary")
SUMMARY_ROOT = REPOSITORY_ROOT / "data" / "summaries"


class RecordingRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> CommandResult:
        self.calls.append((command, cwd))
        return self.responses.pop(0)


def result(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)


def make_publisher(runner: RecordingRunner) -> SummaryPublisher:
    config = PublishingConfig(
        repository_root=REPOSITORY_ROOT,
        summary_root=SUMMARY_ROOT,
        site_root="https://yamopeng0918.github.io/AI-Summary/",
        github_repository="yamopeng0918/AI-Summary",
        workflow_name="Deploy to GitHub Pages",
    )
    return SummaryPublisher(
        config=config,
        repository=object(),
        add_summary=lambda _url: None,
        run_command=runner,
        fetch_json=lambda _url: {},
        fetch_text=lambda _url: (200, ""),
        sleep=lambda _seconds: None,
        now=lambda: 0,
    )


def expected_commands() -> list[list[str]]:
    return [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "branch", "--show-current"],
        ["git", "status", "--porcelain", "--untracked-files=no"],
        ["git", "fetch", "origin", "master"],
        ["git", "rev-list", "--left-right", "--count", "master...origin/master"],
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
    assert raised.value.message == "fatal: unsafe details"
