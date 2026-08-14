"""Testable local publishing safeguards."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, TypeAlias


@dataclass
class PublishError(Exception):
    """A safe publishing failure tied to its workflow stage."""

    stage: str
    message: str


@dataclass
class CommandResult:
    """The relevant result of a command run by the publisher."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner: TypeAlias = Callable[[Sequence[str], Path], CommandResult]


@dataclass
class PublishingConfig:
    """Settings for a single repository's publishing workflow."""

    repository_root: Path
    summary_root: Path
    site_root: str
    github_repository: str
    workflow_name: str
    poll_attempts: int = 30
    poll_delay_seconds: float = 10


class SummaryPublisher:
    """Coordinates publication while keeping external effects injectable."""

    def __init__(
        self,
        config: PublishingConfig,
        repository: Any,
        add_summary: Callable[[str], Any],
        run_command: CommandRunner,
        fetch_json: Callable[[str], Any],
        fetch_text: Callable[[str], Any],
        sleep: Callable[[float], None],
        now: Callable[[], Any],
    ) -> None:
        self.config = config
        self.repository = repository
        self.add_summary = add_summary
        self.run_command = run_command
        self.fetch_json = fetch_json
        self.fetch_text = fetch_text
        self.sleep = sleep
        self.now = now

    def preflight(self) -> None:
        """Require the clean, up-to-date master repository needed for publishing."""
        root = self._run_checked(
            ["git", "rev-parse", "--show-toplevel"], "preflight", self.config.repository_root
        ).stdout.strip()
        if Path(root) != self.config.repository_root:
            raise PublishError("preflight", "run from the repository root")

        branch = self._run_checked(
            ["git", "branch", "--show-current"], "preflight", self.config.repository_root
        ).stdout.strip()
        if branch != "master":
            raise PublishError("preflight", "run from the master branch")

        tracked_status = self._run_checked(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            "preflight",
            self.config.repository_root,
        ).stdout
        if tracked_status:
            raise PublishError("preflight", "tracked changes must be committed")

        self._run_checked(["git", "fetch", "origin", "master"], "preflight", self.config.repository_root)
        remote_state = self._run_checked(
            ["git", "rev-list", "--left-right", "--count", "master...origin/master"],
            "preflight",
            self.config.repository_root,
        ).stdout.strip()
        if remote_state != "0\t0":
            raise PublishError("preflight", "local master must match origin/master")

    def _run_checked(self, command: Sequence[str], stage: str, cwd: Path) -> CommandResult:
        result = self.run_command(command, cwd)
        if result.returncode != 0:
            raise PublishError(stage, "git command failed")
        return result
