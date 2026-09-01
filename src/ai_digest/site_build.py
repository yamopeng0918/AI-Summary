"""Local GitHub Pages build orchestration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from ai_digest.domain import DigestError


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner: TypeAlias = Callable[[Sequence[str], Path], CommandResult]


class SiteBuildService:
    def __init__(
        self,
        repository_root: Path,
        run_command: CommandRunner,
        platform: str,
        python_executable: str,
        on_progress: Callable[[str], None],
    ) -> None:
        self.repository_root = repository_root
        self.run_command = run_command
        self.platform = platform
        self.python_executable = python_executable
        self.on_progress = on_progress

    @staticmethod
    def _failure(step: str) -> DigestError:
        message = (
            "site build command failed"
            if step == "build"
            else "site verification failed"
        )
        return DigestError("deploy", "SITE_BUILD_FAILED", message, False)

    def run(self) -> Path:
        npm = "npm.cmd" if self.platform == "win32" else "npm"
        commands = [
            ([npm, "run", "build:pages"], self.repository_root / "site"),
            (
                [
                    self.python_executable,
                    "scripts/verify_deployment.py",
                    "--tracked",
                    "--dist",
                    "site/dist",
                    "--base",
                    "/AI-Summary/",
                ],
                self.repository_root,
            ),
        ]
        for step, (command, cwd) in zip(("build", "verify"), commands, strict=True):
            self.on_progress(step)
            try:
                result = self.run_command(command, cwd)
            except OSError:
                raise self._failure(step) from None
            if result.returncode != 0:
                raise self._failure(step)
        return (self.repository_root / "site" / "dist").resolve()
