"""Safe deployment of committed AI Digest Pages content."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Literal, Protocol, TypeAlias

from ai_digest.domain import DigestError
from ai_digest.site_build import CommandResult

DEFAULT_SITE_URL = "https://yamopeng0918.github.io/AI-Summary/"
DEFAULT_GITHUB_REPOSITORY = "yamopeng0918/AI-Summary"
DEFAULT_WORKFLOW_NAME = "Deploy to GitHub Pages"

CommandRunner: TypeAlias = Callable[[Sequence[str], Path], CommandResult]
JsonFetcher: TypeAlias = Callable[[str], Any]
ProgressCallback: TypeAlias = Callable[[str, str | None], None]


class BuildService(Protocol):
    def run(self) -> Path: ...


@dataclass(frozen=True)
class DeployResult:
    commit_sha: str
    workflow_url: str
    site_url: str
    push_status: Literal["pushed", "unchanged"]


class DeployService:
    def __init__(
        self,
        repository_root: Path,
        site_build_service: BuildService,
        run_command: CommandRunner,
        fetch_json: JsonFetcher,
        sleep: Callable[[float], None],
        on_progress: ProgressCallback,
        *,
        github_repository: str = DEFAULT_GITHUB_REPOSITORY,
        workflow_name: str = DEFAULT_WORKFLOW_NAME,
        site_url: str = DEFAULT_SITE_URL,
        poll_attempts: int = 30,
        poll_delay_seconds: float = 10,
    ) -> None:
        self.repository_root = repository_root
        self.site_build_service = site_build_service
        self.run_command = run_command
        self.fetch_json = fetch_json
        self.sleep = sleep
        self.on_progress = on_progress
        self.github_repository = github_repository
        self.workflow_name = workflow_name
        self.site_url = site_url
        self.poll_attempts = poll_attempts
        self.poll_delay_seconds = poll_delay_seconds

    @staticmethod
    def _error(code: str, message: str, retryable: bool = False) -> DigestError:
        return DigestError("deploy", code, message, retryable)

    def _checked(self, command: Sequence[str], code: str, message: str) -> CommandResult:
        try:
            result = self.run_command(command, self.repository_root)
        except OSError:
            raise self._error(code, message) from None
        if result.returncode != 0:
            raise self._error(code, message)
        return result

    def run(self) -> DeployResult:
        self.on_progress("preflight", None)
        root = self._checked(
            ["git", "rev-parse", "--show-toplevel"],
            "DEPLOY_PREFLIGHT_FAILED",
            "deployment preflight failed",
        ).stdout.strip()
        if Path(root) != self.repository_root:
            raise self._error("DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed")
        branch = self._checked(
            ["git", "branch", "--show-current"],
            "DEPLOY_PREFLIGHT_FAILED",
            "deployment preflight failed",
        ).stdout.strip()
        if branch != "master":
            raise self._error("DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed")
        status = self._checked(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            "DEPLOY_PREFLIGHT_FAILED",
            "deployment preflight failed",
        ).stdout
        if status:
            raise self._error("DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed")
        self._checked(
            ["git", "fetch", "origin", "master"],
            "DEPLOY_PUSH_FAILED",
            "deployment fetch failed",
        )
        counts = self._checked(
            ["git", "rev-list", "--left-right", "--count", "master...origin/master"],
            "DEPLOY_PREFLIGHT_FAILED",
            "deployment preflight failed",
        ).stdout.split()
        try:
            local_only, remote_only = (int(value) for value in counts)
        except (TypeError, ValueError):
            raise self._error(
                "DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed"
            ) from None
        if local_only < 0 or remote_only != 0:
            raise self._error("DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed")
        push_status: Literal["pushed", "unchanged"] = "unchanged"
        self.site_build_service.run()
        if local_only > 0:
            self._checked(
                ["git", "push", "origin", "master"],
                "DEPLOY_PUSH_FAILED",
                "deployment push failed",
            )
            push_status = "pushed"
        commit = self._checked(
            ["git", "rev-parse", "HEAD"],
            "DEPLOY_PREFLIGHT_FAILED",
            "deployment preflight failed",
        ).stdout.strip()
        self.on_progress("push", push_status)
        self.on_progress("workflow", None)
        workflow_url = self._wait_for_workflow(commit)
        self.on_progress("public", None)
        self._checked(
            [sys.executable, "scripts/smoke_pages.py"],
            "DEPLOY_PUBLIC_FAILED",
            "public deployment verification failed",
        )
        return DeployResult(commit, workflow_url, self.site_url, push_status)

    def _wait_for_workflow(self, commit_sha: str) -> str:
        url = (
            f"https://api.github.com/repos/{self.github_repository}/actions/runs"
            f"?head_sha={commit_sha}&per_page=20"
        )
        try:
            payload = self.fetch_json(url)
        except Exception:
            raise self._error(
                "DEPLOY_WORKFLOW_FAILED",
                "workflow status request failed",
                True,
            ) from None
        if not isinstance(payload, dict):
            raise self._error(
                "DEPLOY_WORKFLOW_FAILED", "deployment workflow timed out", True
            )
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise self._error(
                "DEPLOY_WORKFLOW_FAILED", "deployment workflow timed out", True
            )
        for run in runs:
            if not isinstance(run, dict):
                continue
            if run.get("head_sha") != commit_sha:
                continue
            if run.get("name") != self.workflow_name:
                continue
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                raise self._error(
                    "DEPLOY_WORKFLOW_FAILED", "deployment workflow failed"
                )
            workflow_url = run.get("html_url")
            if isinstance(workflow_url, str) and workflow_url:
                return workflow_url
        raise self._error(
            "DEPLOY_WORKFLOW_FAILED", "deployment workflow timed out", True
        )
