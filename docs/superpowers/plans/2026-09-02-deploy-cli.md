# Deploy CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a key-free `ai-digest deploy` command that safely deploys already committed `master` content, reuses the local Pages gates, waits for the matching GitHub Pages workflow, and verifies the public site.

**Architecture:** A new `DeployService` owns Git preflight, fast-forward push decisions, workflow polling, and public smoke orchestration through injected boundaries. It composes the existing `SiteBuildService`; the deploy composition injects one capturing runner into Git, npm/Astro build, verifier, and public smoke so Typer emits JSON Lines only. The standalone `build-site` composition retains its live diagnostics. No summary provider, classifier, repository mutation, commit, or force push is involved.

**Tech Stack:** Python 3.12+, Typer, HTTPX, subprocess, pytest, Git, GitHub Actions public REST API, existing Astro/Vitest build and `scripts/smoke_pages.py`.

## Global Constraints

- Follow strict TDD: write one minimal behavior test, observe the intended RED, implement the minimum, and rerun before adding the next behavior.
- `deploy` accepts no arguments and fixes branch `master`, remote `origin`, workflow name `Deploy to GitHub Pages`, Pages root `https://yamopeng0918.github.io/AI-Summary/`, and base path `/AI-Summary/`.
- Never run `git add`, `git commit`, `git reset`, checkout, pull, rebase, force push, `workflow_dispatch`, provider initialization, classifier initialization, or summary mutation.
- Ignore untracked files, but reject any staged or unstaged tracked-file change.
- Allow `master` to equal `origin/master` or be strictly ahead; reject any state with remote-only commits.
- Run the existing `SiteBuildService` before any push.
- Query the public GitHub Actions API without a token and run the existing public smoke script only after the matching workflow succeeds.
- Do not expose subprocess output, HTTP response bodies, exception text, environment variables, credentials, or sensitive local paths in `DigestError`.
- `deploy` stdout/stderr must contain structured JSON Lines only; capture and suppress every Git, npm/Astro, verifier, and public-smoke subprocess stream. Keep standalone `build-site` live diagnostics unchanged.
- Automated tests must not require a real network, GitHub account, paid API, or real push.
- A real `ai-digest deploy` run requires a fresh explicit user authorization after all local gates pass.
- Preserve all unrelated tracked and untracked user files.

---

## File Structure

- Create `src/ai_digest/deployment.py`: immutable deploy result, Git state parsing, safe command mapping, build composition, workflow polling, and public smoke orchestration.
- Create `tests/test_deployment.py`: isolated service tests with recording command, build, workflow, sleep, and progress fakes.
- Modify `src/ai_digest/cli.py`: production Git/smoke runner, public workflow fetcher, deploy factory injection, and `deploy` command.
- Modify `tests/test_cli.py`: output contract, safe failure, no-argument behavior, falsey injection, and key-free lazy dependency tests.
- Modify `README.md`, `progress.md`, and `todo.md`: user contract, verified evidence, remaining real-deployment gate, and final acceptance status.

---

### Task 1: Git preflight, build, and push decision service

**Files:**
- Create: `tests/test_deployment.py`
- Create: `src/ai_digest/deployment.py`

**Interfaces:**
- Consumes: `ai_digest.domain.DigestError`, `ai_digest.site_build.CommandResult`, an object exposing `run() -> Path`, and a command runner `Callable[[Sequence[str], Path], CommandResult]`.
- Produces: `DeployResult(commit_sha: str, workflow_url: str, site_url: str, push_status: Literal["pushed", "unchanged"])` and `DeployService.run() -> DeployResult`.
- `DeployService.__init__` accepts `repository_root`, `site_build_service`, `run_command`, `fetch_json`, `sleep`, `on_progress`, plus fixed-default workflow/site/poll values. The progress callback signature is `Callable[[str, str | None], None]`.

- [ ] **Step 1: Add the first RED test for a synchronized, clean master**

Create `tests/test_deployment.py` with reusable fakes and the first contract:

```python
from pathlib import Path

from ai_digest.deployment import DeployService
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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py::test_synchronized_master_builds_without_push -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ai_digest.deployment'`.

- [ ] **Step 3: Implement the minimal types, preflight, build, synchronized path, and safe public command**

Create `src/ai_digest/deployment.py` with these stable public types and initial flow:

```python
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
        if counts != ["0", "0"]:
            raise self._error("DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed")
        self.site_build_service.run()
        commit = self._checked(
            ["git", "rev-parse", "HEAD"],
            "DEPLOY_PREFLIGHT_FAILED",
            "deployment preflight failed",
        ).stdout.strip()
        self.on_progress("push", "unchanged")
        self.on_progress("workflow", None)
        workflow_url = self._wait_for_workflow(commit)
        self.on_progress("public", None)
        self._checked(
            [sys.executable, "scripts/smoke_pages.py"],
            "DEPLOY_PUBLIC_FAILED",
            "public deployment verification failed",
        )
        return DeployResult(commit, workflow_url, self.site_url, "unchanged")

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
```

Task 2 will replace this one-request implementation with bounded polling under new RED tests.

- [ ] **Step 4: Run the first test and verify GREEN**

Run the Step 2 command again. Expected: `1 passed`.

- [ ] **Step 5: Add RED tests for ahead push, dirty/behind/diverged rejection, untracked tolerance, and sanitization**

Append parameterized tests that assert the exact commands and boundaries:

```python
import pytest

from ai_digest.domain import DigestError


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
```

The test helper `make_service()` must inject a successful matching workflow payload and a successful smoke response; `runner_for_success()` must use only deterministic `CommandResult` instances and record the build boundary without a real Git repository.

- [ ] **Step 6: Run service tests and confirm the new RED failures**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py -v
```

Expected: ahead-state and push-order tests fail because the initial implementation only accepts `0 0`; existing synchronized test remains green.

- [ ] **Step 7: Implement exact ahead/behind parsing and fail-safe push**

Replace the synchronized-only counts branch with:

```python
        try:
            local_only, remote_only = (int(value) for value in counts)
        except (TypeError, ValueError):
            raise self._error(
                "DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed"
            ) from None
        if local_only < 0 or remote_only != 0:
            raise self._error(
                "DEPLOY_PREFLIGHT_FAILED", "deployment preflight failed"
            )
        push_status: Literal["pushed", "unchanged"] = "unchanged"
        self.site_build_service.run()
        if local_only > 0:
            self._checked(
                ["git", "push", "origin", "master"],
                "DEPLOY_PUSH_FAILED",
                "deployment push failed",
            )
            push_status = "pushed"
        self.on_progress("push", push_status)
```

Return the computed `push_status`. Keep `git status --porcelain --untracked-files=no` unchanged so untracked files remain outside the decision.

- [ ] **Step 8: Run Task 1 tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py -k "preflight or synchronized or ahead or tracked or push" -v
```

Expected: all selected tests pass, including safe `OSError` and nonzero-result mappings with no raw marker leakage.

- [ ] **Step 9: Commit Task 1**

```powershell
git add -- src/ai_digest/deployment.py tests/test_deployment.py
git diff --cached --check
git commit -m "feat: add safe deployment service"
```

---

### Task 2: Workflow polling and public smoke boundaries

**Files:**
- Modify: `tests/test_deployment.py`
- Modify: `src/ai_digest/deployment.py`

**Interfaces:**
- Consumes: `DeployService.fetch_json(url) -> object`, `sleep(seconds)`, fixed repository/workflow names, current HEAD, and the injected command runner.
- Produces: `_wait_for_workflow(commit_sha: str) -> str` and safe workflow/public `DigestError` behavior.

- [ ] **Step 1: Add RED tests for completed success, in-progress polling, explicit failure, request failure, timeout, and public smoke failure**

Add a sequence fetcher and tests:

```python
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


def workflow(status: str, conclusion=None, *, sha: str = HEAD) -> dict[str, object]:
    return {
        "head_sha": sha,
        "name": "Deploy to GitHub Pages",
        "status": status,
        "conclusion": conclusion,
        "html_url": "https://github.example/run/1",
    }


def test_workflow_in_progress_is_polled_until_success() -> None:
    fetcher = SequenceFetcher([
        {"workflow_runs": [workflow("in_progress")]},
        {"workflow_runs": [workflow("completed", "success")]},
    ])
    sleeps: list[float] = []
    service = make_service(
        runner_for_success(), fetch_json=fetcher, sleep=sleeps.append,
        poll_attempts=2, poll_delay_seconds=0.25,
    )

    result = service.run()

    assert result.workflow_url == "https://github.example/run/1"
    assert sleeps == [0.25]
    assert all(f"head_sha={HEAD}" in url for url in fetcher.urls)


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
```

- [ ] **Step 2: Run the Task 2 tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py -k "workflow or public" -v
```

Expected: polling, retryable classification, URL filtering, or public retryability tests fail against the Task 1 minimal workflow implementation.

- [ ] **Step 3: Implement safe matching workflow polling**

Implement:

```python
    def _wait_for_workflow(self, commit_sha: str) -> str:
        url = (
            f"https://api.github.com/repos/{self.github_repository}/actions/runs"
            f"?head_sha={commit_sha}&per_page=20"
        )
        for attempt in range(self.poll_attempts):
            try:
                payload = self.fetch_json(url)
            except Exception:
                raise self._error(
                    "DEPLOY_WORKFLOW_FAILED",
                    "workflow status request failed",
                    True,
                ) from None
            run = self._matching_workflow(payload, commit_sha)
            if run is not None and run.get("status") == "completed":
                if run.get("conclusion") != "success":
                    raise self._error(
                        "DEPLOY_WORKFLOW_FAILED", "deployment workflow failed"
                    )
                workflow_url = run.get("html_url")
                if not isinstance(workflow_url, str) or not workflow_url:
                    raise self._error(
                        "DEPLOY_WORKFLOW_FAILED", "deployment workflow failed"
                    )
                return workflow_url
            if attempt + 1 < self.poll_attempts:
                self.sleep(self.poll_delay_seconds)
        raise self._error(
            "DEPLOY_WORKFLOW_FAILED", "deployment workflow timed out", True
        )

    def _matching_workflow(
        self, payload: object, commit_sha: str
    ) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            return None
        for run in runs:
            if not isinstance(run, dict):
                continue
            if run.get("head_sha") != commit_sha:
                continue
            if run.get("name") != self.workflow_name:
                continue
            return run
        return None
```

Change public command handling to map nonzero/OSError to `DEPLOY_PUBLIC_FAILED`, fixed message `public deployment verification failed`, and `retryable=True`. Do not use the generic `_checked()` default retryability for this command.

- [ ] **Step 4: Run the complete service tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py -v
```

Expected: all service tests pass with no external network or Git mutation.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- src/ai_digest/deployment.py tests/test_deployment.py
git diff --cached --check
git commit -m "feat: verify deployment workflow and public site"
```

---

### Task 3: Typer `deploy` command and production wiring

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_digest/cli.py`

**Interfaces:**
- Consumes: `DeployService`, `DeployResult`, `CommandResult`, `SiteBuildService`, `subprocess.run`, `httpx.get`, `time.sleep`, `sys.executable`, and `Path.cwd()`.
- Produces: `_deploy_service(on_progress) -> DeployService`, optional `create_app(..., deploy_service_factory=...)`, and no-argument `deploy`.
- Factory signature: `Callable[[Callable[[str, str | None], None]], DeployService]`.

- [ ] **Step 1: Add RED CLI success and failure tests with an injected fake**

Add imports and fake:

```python
from ai_digest.deployment import DeployResult


class FakeDeployService:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error

    def run(self) -> DeployResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result
```

Add tests:

```python
def test_deploy_emits_ordered_progress_and_complete_result(tmp_path: Path) -> None:
    expected = DeployResult(
        commit_sha="a" * 40,
        workflow_url="https://github.example/run/1",
        site_url="https://yamopeng0918.github.io/AI-Summary/",
        push_status="unchanged",
    )

    def factory(on_progress):
        for step, status in (
            ("preflight", None), ("build", None), ("verify", None),
            ("push", "unchanged"), ("workflow", None), ("public", None),
        ):
            on_progress(step, status)
        return FakeDeployService(result=expected)

    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(tmp_path),
        lambda: NOW,
        deploy_service_factory=factory,
    )

    result = CliRunner().invoke(app, ["deploy"])

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1] == {
        "stage": "complete",
        "commit": "a" * 40,
        "workflow": "https://github.example/run/1",
        "site": "https://yamopeng0918.github.io/AI-Summary/",
    }
    assert events[3] == {
        "stage": "deploy", "step": "push", "status": "unchanged"
    }


def test_deploy_reports_safe_structured_error(tmp_path: Path) -> None:
    error = DigestError(
        "deploy", "DEPLOY_WORKFLOW_FAILED", "deployment workflow failed", False
    )
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(tmp_path),
        lambda: NOW,
        deploy_service_factory=lambda _progress: FakeDeployService(error=error),
    )

    result = CliRunner().invoke(app, ["deploy"])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == error.as_dict()
```

- [ ] **Step 2: Run focused CLI tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -k "deploy" -v
```

Expected: tests fail because `create_app` has no `deploy_service_factory` and no `deploy` command.

- [ ] **Step 3: Add the injectable command and production adapters**

In `src/ai_digest/cli.py`, import `time`, deployment types, and add:

```python
def _deploy_service(
    on_progress: Callable[[str, str | None], None],
) -> DeployService:
    repository_root = Path.cwd().resolve()

    def run_command(command, cwd: Path) -> SiteBuildCommandResult:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        return SiteBuildCommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def fetch_json(url: str) -> object:
        response = httpx.get(
            url,
            headers={"User-Agent": "AI-Digest-Deployer/1.0"},
            timeout=15.0,
        )
        response.raise_for_status()
        return response.json()

    build_service = SiteBuildService(
        repository_root=repository_root,
        run_command=run_command,
        platform=sys.platform,
        python_executable=sys.executable,
        on_progress=lambda step: on_progress(step, None),
    )
    return DeployService(
        repository_root,
        build_service,
        run_command,
        fetch_json,
        time.sleep,
        on_progress,
    )
```

Extend `create_app` with:

```python
    deploy_service_factory: Callable[
        [Callable[[str, str | None], None]], DeployService
    ] | None = None,
```

Resolve by explicit `is not None`, matching the hardened build-site factory. Register:

```python
    @application.command("deploy")
    def deploy() -> None:
        """Deploy committed master content and verify GitHub Pages."""
        try:
            def progress(step: str, status: str | None = None) -> None:
                payload: dict[str, object] = {"stage": "deploy", "step": step}
                if status is not None:
                    payload["status"] = status
                _emit(payload)

            result = deploy_factory(progress).run()
            _emit({
                "stage": "complete",
                "commit": result.commit_sha,
                "workflow": result.workflow_url,
                "site": result.site_url,
            })
        except DigestError as error:
            report_error(error)
```

- [ ] **Step 4: Run focused CLI tests and verify GREEN**

Run the Step 2 command again. Expected: success and error tests pass.

- [ ] **Step 5: Add RED/contract tests for no arguments, falsey injection, and production laziness**

Add tests that:

```python
def test_deploy_rejects_extra_arguments(tmp_path: Path) -> None:
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(tmp_path),
        lambda: NOW,
        deploy_service_factory=lambda _progress: FakeDeployService(
            result=DeployResult("a" * 40, "https://run", "https://site/", "unchanged")
        ),
    )
    assert CliRunner().invoke(app, ["deploy", "unexpected"]).exit_code == 2
```

Add the falsey-injection regression explicitly:

```python
def test_deploy_uses_falsey_injected_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    injected_calls = 0
    default_calls = 0

    class FalseyFactory:
        def __bool__(self) -> bool:
            return False

        def __call__(self, _progress) -> FakeDeployService:
            nonlocal injected_calls
            injected_calls += 1
            return FakeDeployService(
                result=DeployResult(
                    "a" * 40, "https://run", "https://site/", "unchanged"
                )
            )

    def default_factory(_progress) -> FakeDeployService:
        nonlocal default_calls
        default_calls += 1
        return FakeDeployService(
            result=DeployResult("b" * 40, "https://run", "https://site/", "unchanged")
        )

    monkeypatch.setattr(cli, "_deploy_service", default_factory)
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(tmp_path),
        lambda: NOW,
        deploy_service_factory=FalseyFactory(),
    )

    result = CliRunner().invoke(app, ["deploy"])

    assert result.exit_code == 0
    assert injected_calls == 1
    assert default_calls == 0
```

For production laziness, patch `cli._provider`, `cli._classifier`, and `cli._repository` to raise `AssertionError`; patch `cli.httpx.get`, `cli.subprocess.run`, and `cli.time.sleep` with deterministic fakes that return the exact preflight, synchronized-state, matching-workflow, and smoke results. Invoke `cli.app` with `deploy`, assert exit `0`, assert neither lazy dependency was called, assert the Git command list contains no `add`, `commit`, `reset`, `checkout`, `pull`, `rebase`, or force option, assert the workflow request contains the current fake HEAD, and assert every subprocess call receives an argument sequence rather than `shell=True`. Make the fake npm/Astro and verifier commands produce noisy stdout/stderr whenever `capture_output=True` is absent, then assert the complete ordered `pushed` and `unchanged` event sequences and that both CLI streams contain JSON Lines only. Retain a separate production `build-site` assertion showing its live diagnostics are still visible.

- [ ] **Step 6: Run all deploy CLI and directly related tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py tests/test_site_build.py tests/test_cli.py -v
```

Expected: all tests pass; only the documented third-party `google-genai` deprecation warning is acceptable.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- src/ai_digest/cli.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: expose deploy CLI command"
```

---

### Task 4: Documentation, full local gates, review, and authorized live acceptance

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: verified `ai-digest deploy` behavior and actual command outputs.
- Produces: accurate operating instructions and project status without claiming remote completion before evidence exists.

- [ ] **Step 1: Run complete local regression gates before documentation claims**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
Push-Location site
npm.cmd test
Pop-Location
.\.venv\Scripts\ai-digest.exe build-site
.\.venv\Scripts\python.exe scripts\verify_deployment.py --tracked --dist site\dist --base /AI-Summary/
git diff --check
```

Expected: all Python and Vitest tests pass; Astro reports zero diagnostics; `build-site` emits build, verify, complete; both deployment verifiers and diff check exit `0`. Record exact counts from this run.

- [ ] **Step 2: Request an independent code review and resolve every Critical/Important finding**

Review the diff from design commit `602e4e1` through current HEAD against `docs/superpowers/specs/2026-09-02-deploy-cli-design.md`. Rerun affected focused tests after each accepted correction; do not proceed with unresolved Critical or Important findings.

- [ ] **Step 3: Update README and progress truthfully for local completion**

Document:

```markdown
ai-digest deploy
```

State that it deploys only committed `master`, ignores untracked files, rejects tracked changes/behind/diverged state, runs existing local gates, pushes only when strictly ahead, reuses an existing matching successful workflow when synchronized, then runs public smoke. Explicitly state that it never commits, force pushes, dispatches a duplicate workflow, initializes a provider, or deploys non-`master` branches.

In `progress.md`, record implementation SHAs, review result, exact local gate counts, and whether live acceptance remains pending. In `todo.md`, keep deploy unchecked until Step 6 succeeds.

- [ ] **Step 4: Commit locally verified documentation**

```powershell
git add -- README.md progress.md todo.md
git diff --cached --check
git commit -m "docs: record deploy CLI workflow"
```

- [ ] **Step 5: Stop and request fresh explicit authorization for the real deploy**

Report the exact commits that `master` is ahead of `origin/master`, the fresh test/build/verifier results, and that `ai-digest deploy` will push them and trigger GitHub Pages. Do not run the command until the user explicitly authorizes this specific live action.

- [ ] **Step 6: After authorization, run one real acceptance and preserve all failure state**

Run from repository root:

```powershell
.\.venv\Scripts\ai-digest.exe deploy
```

Expected: preflight, build, verify, `push: pushed`, workflow, public, complete; exit `0`; returned commit equals local HEAD; workflow URL is for that SHA; public smoke succeeds. If push succeeds but later stages fail, do not reset, delete, or rewrite commits—record the exact remaining retryable stage.

- [ ] **Step 7: Record remote evidence only after it exists**

Update `progress.md` with the live commit, workflow run URL/ID, conclusion, and public smoke result. Mark the deploy checkbox complete in `todo.md` only if all live stages succeeded.

- [ ] **Step 8: Verify and commit the final acceptance record**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_deployment.py tests/test_cli.py -v
.\.venv\Scripts\python.exe scripts\verify_deployment.py --tracked --dist site\dist --base /AI-Summary/
git diff --check
git add -- progress.md todo.md
git diff --cached --check
git commit -m "docs: record deploy CLI acceptance"
```

- [ ] **Step 9: Request authorization before pushing the acceptance-record commit**

The live deploy in Step 6 cannot include the documentation created afterward. Ask before the second `git push origin master`; then wait for that commit's matching workflow and confirm the public site again. Do not silently push it.
