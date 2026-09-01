# Build-site CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ai-digest build-site` as a key-free local command that builds the GitHub Pages site and passes both artifact/base-path and tracked/dist sensitive-data gates.

**Architecture:** A focused `SiteBuildService` coordinates the existing `npm run build:pages` and deployment verifier through an injectable command runner. Typer only wires the service, emits JSON Lines progress, and maps the service's existing `DigestError` contract to exit code 1; Astro generation and verifier logic remain their current sources of truth.

**Tech Stack:** Python 3.12+, Typer, pytest, subprocess, Astro 7, Vitest, npm, existing `scripts/verify_deployment.py`.

## Global Constraints

- Follow strict TDD: add one minimal failing behavior test, observe the expected failure, implement the minimum, and rerun before continuing.
- `build-site` accepts no options and fixes the site root to `site`, output to `site/dist`, and Pages base path to `/AI-Summary/`.
- Use `npm.cmd` on Windows and `npm` on other platforms; use the active `sys.executable` for the verifier.
- Do not run `npm ci`, install dependencies, access the network, initialize an AI provider or classifier, modify summary JSON, mutate Git state, create commits, push, or deploy. The required verifier may run read-only `git ls-files` to scan tracked files.
- Keep subprocess output attached to the interactive terminal; never include stdout, stderr, exception text, environment variables, or credentials in structured errors.
- All failures use `stage="deploy"`, `code="SITE_BUILD_FAILED"`, `retryable=False`; build and verification messages remain distinct.
- Preserve all existing untracked user files and unrelated working-tree changes.
- Execute the real CLI from a worktree-local virtual environment installed with `pip install -e . --no-deps`; do not use the root checkout's editable console script.

---

## File Structure

- Create `src/ai_digest/site_build.py`: platform-aware command construction, ordered execution, safe failure mapping, and successful dist-path result.
- Create `tests/test_site_build.py`: isolated service contract and error-sanitization tests using a recording runner.
- Modify `src/ai_digest/cli.py`: production runner/factory, injectable service factory, and `build-site` Typer command.
- Modify `tests/test_cli.py`: command output, exit behavior, no-argument contract, and key-free dependency isolation.
- Modify `README.md`: user-facing `build-site` command, prerequisites, outputs, and explicit non-deployment boundary.
- Modify `progress.md`: verified outcome, evidence, risks, and next step.
- Modify `todo.md`: mark only `build-site` complete while leaving `deploy` unchecked.

---

### Task 1: Site build service

**Files:**
- Create: `tests/test_site_build.py`
- Create: `src/ai_digest/site_build.py`

**Interfaces:**
- Consumes: `ai_digest.domain.DigestError`, `pathlib.Path`, a command runner with signature `Callable[[Sequence[str], Path], CommandResult]`, a platform string, an active Python executable string, and a progress callback `Callable[[str], None]`.
- Produces: `CommandResult(returncode: int, stdout: str = "", stderr: str = "")` and `SiteBuildService.run() -> Path`.
- `SiteBuildService.__init__` signature: `(repository_root: Path, run_command: CommandRunner, platform: str, python_executable: str, on_progress: Callable[[str], None])`.

- [ ] **Step 1: Add the first failing service test for the ordered Windows success path**

Create `tests/test_site_build.py` with a recording runner and this contract:

```python
from pathlib import Path

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
```

- [ ] **Step 2: Run the first service test and verify the red state**

Run:

```powershell
python -m pytest tests/test_site_build.py::test_build_runs_pages_build_then_complete_verifier_on_windows -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ai_digest.site_build'`.

- [ ] **Step 3: Implement the minimal ordered success path**

Create `src/ai_digest/site_build.py`:

```python
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
            result = self.run_command(command, cwd)
            if result.returncode != 0:
                raise self._failure(step)
        return (self.repository_root / "site" / "dist").resolve()
```

- [ ] **Step 4: Run the first service test and verify green**

Run the Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 5: Add failing service tests for cross-platform selection, fail-fast behavior, and sanitization**

Append tests that assert:

```python
import pytest

from ai_digest.domain import DigestError


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
```

- [ ] **Step 6: Run the expanded service tests and verify the intended red state**

Run:

```powershell
python -m pytest tests/test_site_build.py -v
```

Expected: the `OSError` parameterized cases fail because the exception is not yet converted; all non-exception cases pass.

- [ ] **Step 7: Add minimal command-start exception mapping**

Wrap only the runner call in `SiteBuildService.run()`:

```python
            try:
                result = self.run_command(command, cwd)
            except OSError:
                raise self._failure(step) from None
```

Keep the nonzero-return branch after this block; both failure paths must call the same `_failure(step)` helper.

- [ ] **Step 8: Run the full service test file**

Run:

```powershell
python -m pytest tests/test_site_build.py -v
```

Expected: all service tests pass.

- [ ] **Step 9: Commit the independently tested service**

Run:

```powershell
git add -- src/ai_digest/site_build.py tests/test_site_build.py
git diff --cached --check
git commit -m "feat: add local site build service"
```

Expected: one commit containing only the service and its tests.

---

### Task 2: Typer `build-site` command

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_digest/cli.py`

**Interfaces:**
- Consumes: `SiteBuildService`, `CommandResult`, `subprocess.run`, `sys.platform`, `sys.executable`, and repository root `Path.cwd()` in production wiring.
- Produces: optional `create_app(..., site_build_service_factory=...)`, `_site_build_service(on_progress) -> SiteBuildService`, and the no-argument `build-site` command.
- Factory signature: `Callable[[Callable[[str], None]], SiteBuildService]`.

- [ ] **Step 1: Add failing CLI success and failure tests with an injected fake service**

Add a fake near existing CLI fakes:

```python
class FakeSiteBuildService:
    def __init__(
        self,
        result: Path | None = None,
        error: DigestError | None = None,
    ) -> None:
        self.result = result
        self.error = error

    def run(self) -> Path:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result
```

Add tests using a factory that records the supplied callback:

```python
def test_build_site_emits_ordered_progress_and_complete_path(tmp_path: Path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    dist = (tmp_path / "site" / "dist").resolve()

    def factory(on_progress):
        on_progress("build")
        on_progress("verify")
        return FakeSiteBuildService(result=dist)

    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: repository,
        lambda: NOW,
        site_build_service_factory=factory,
    )

    result = CliRunner().invoke(app, ["build-site"])

    assert result.exit_code == 0
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        {"stage": "deploy", "step": "build"},
        {"stage": "deploy", "step": "verify"},
        {"stage": "complete", "path": str(dist)},
    ]


def test_build_site_reports_safe_structured_error(tmp_path: Path) -> None:
    error = DigestError(
        "deploy", "SITE_BUILD_FAILED", "site verification failed", False
    )
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(tmp_path),
        lambda: NOW,
        site_build_service_factory=lambda _on_progress: FakeSiteBuildService(error=error),
    )

    result = CliRunner().invoke(app, ["build-site"])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == error.as_dict()
```

- [ ] **Step 2: Run both CLI tests and verify red**

Run:

```powershell
python -m pytest tests/test_cli.py -k "build_site" -v
```

Expected: both fail because `create_app` does not accept `site_build_service_factory` and no `build-site` command exists.

- [ ] **Step 3: Add the injectable CLI command with minimal production wiring**

In `src/ai_digest/cli.py`:

```python
from ai_digest.site_build import CommandResult as SiteBuildCommandResult
from ai_digest.site_build import SiteBuildService
```

Add the production factory before `_emit`:

```python
def _site_build_service(on_progress: Callable[[str], None]) -> SiteBuildService:
    def run_command(command, cwd: Path) -> SiteBuildCommandResult:
        completed = subprocess.run(command, cwd=cwd, check=False)
        return SiteBuildCommandResult(returncode=completed.returncode)

    return SiteBuildService(
        repository_root=Path.cwd().resolve(),
        run_command=run_command,
        platform=sys.platform,
        python_executable=sys.executable,
        on_progress=on_progress,
    )
```

Extend `create_app`:

```python
    site_build_service_factory: Callable[
        [Callable[[str], None]], SiteBuildService
    ] | None = None,
```

Resolve the lazy factory inside `create_app`:

```python
    site_build_factory = site_build_service_factory or _site_build_service
```

Register the command before `return application`:

```python
    @application.command("build-site")
    def build_site() -> None:
        """Build and verify the local GitHub Pages site."""
        try:
            service = site_build_factory(
                lambda step: _emit({"stage": "deploy", "step": step})
            )
            path = service.run()
            _emit({"stage": "complete", "path": str(path)})
        except DigestError as error:
            report_error(error)
```

Keep the module-level `app = create_app(...)` call unchanged so it uses the lazy production default.

- [ ] **Step 4: Run focused CLI tests and verify green**

Run the Step 2 command again.

Expected: both tests pass.

- [ ] **Step 5: Add failing contract tests for no arguments and dependency isolation**

Add:

```python
def test_build_site_rejects_extra_arguments(tmp_path: Path) -> None:
    service = FakeSiteBuildService(result=(tmp_path / "site" / "dist").resolve())
    app = create_app(
        lambda on_progress: FakeWorkflow(make_record()),
        lambda: SummaryRepository(tmp_path),
        lambda: NOW,
        site_build_service_factory=lambda _on_progress: service,
    )

    result = CliRunner().invoke(app, ["build-site", "unexpected"])

    assert result.exit_code == 2


def test_production_build_site_does_not_initialize_provider_or_classifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        cli,
        "_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider must stay lazy")),
    )
    monkeypatch.setattr(
        cli,
        "_classifier",
        lambda: (_ for _ in ()).throw(AssertionError("classifier must stay lazy")),
    )
    captured: dict[str, object] = {}

    class FakeCompleted:
        returncode = 0

    def fake_run(command, *, cwd, check):
        captured.setdefault("calls", []).append((list(command), cwd, check))
        return FakeCompleted()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = CliRunner().invoke(cli.app, ["build-site"])

    assert result.exit_code == 0
    assert len(captured["calls"]) == 2
```

- [ ] **Step 6: Run the expanded focused CLI tests**

Run:

```powershell
python -m pytest tests/test_cli.py -k "build_site" -v
```

Expected: all `build_site` tests pass. If the production isolation test reveals eager initialization, make only the factory-resolution change required to preserve laziness and rerun until green.

- [ ] **Step 7: Run all directly related Python tests**

Run:

```powershell
python -m pytest tests/test_site_build.py tests/test_cli.py -v
```

Expected: all tests in both files pass; the only acceptable warning is the already documented third-party `google-genai` deprecation warning.

- [ ] **Step 8: Commit the CLI integration**

Run:

```powershell
git add -- src/ai_digest/cli.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: expose build-site CLI command"
```

Expected: one commit containing only CLI wiring and CLI tests.

---

### Task 3: Documentation, full verification, and progress reconciliation

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: verified `ai-digest build-site` behavior and actual test/build outputs from this task.
- Produces: accurate user instructions and project status; `deploy` remains explicitly incomplete.

- [ ] **Step 1: Run the complete Python regression suite before documentation claims**

Run:

```powershell
python -m pytest
```

Expected: all Python tests pass. Record the exact passed/skipped/warning counts; do not reuse historical counts.

- [ ] **Step 2: Run the complete frontend test suite**

Run from `site`:

```powershell
npm.cmd test
```

Expected: all Vitest files and tests pass. Record exact counts.

- [ ] **Step 3: Run the actual production CLI gate**

Run from repository root using the installed project CLI:

```powershell
& '.\.venv\Scripts\ai-digest.exe' build-site
```

Expected:

- JSON progress contains `build`, then `verify`, then `complete`.
- Astro check reports zero errors.
- Astro creates the page count implied by the currently published records and regenerates OG PNGs in `site/dist/og`.
- Both the internal `build:pages` verifier and the final tracked/dist verifier exit successfully.
- Final JSON path resolves to `<repository>/site/dist`.

- [ ] **Step 4: Update README with the verified command contract**

In the Astro website section, add:

````markdown
在 repository 根目錄可用 Python CLI 執行完整的本機 Pages gate：

```powershell
ai-digest build-site
```

此命令使用既有本機 Node.js dependencies，依序執行 `npm.cmd run build:pages` 與 tracked／`site/dist` 敏感資訊掃描。它不執行 `npm ci`、Git commit、push、GitHub Actions 或部署，也不需要摘要 provider 金鑰；依賴尚未安裝時會明確失敗。
````

Retain the lower-level npm and verifier commands as troubleshooting/manual alternatives.

- [ ] **Step 5: Update project progress without marking deploy complete**

Update `progress.md` with a new topmost `2026-09-01` record containing:

- the two implementation commit SHAs;
- focused and complete Python test counts;
- complete Vitest counts;
- actual `build-site` Astro/page/OG/verifier evidence;
- confirmation that no provider key, network, push, or deployment was used;
- next step: independently design `deploy` before any implementation.

In `todo.md`, replace the combined unchecked item with two independently truthful items:

```markdown
- [x] 實作並驗證 `build-site` 指令；完整證據見 `progress.md` 的 2026-09-01 紀錄。
- [ ] 另行設計、核准並實作 `deploy` 指令。
```

- [ ] **Step 6: Validate documentation consistency and working-tree whitespace**

Run:

```powershell
rg -n "build-site|deploy" README.md progress.md todo.md docs/superpowers/specs/2026-09-01-build-site-cli-design.md
git diff --check
```

Expected: the command, non-deployment boundary, date, and completion state agree across all four files; `git diff --check` exits 0.

- [ ] **Step 7: Re-run the focused tests after documentation edits**

Run:

```powershell
python -m pytest tests/test_site_build.py tests/test_cli.py -v
```

Expected: all focused tests remain green.

- [ ] **Step 8: Commit documentation and status updates**

Run:

```powershell
git add -- README.md progress.md todo.md
git diff --cached --check
git commit -m "docs: record build-site workflow"
```

Expected: one commit containing only the three synchronized documentation files.

- [ ] **Step 9: Perform final repository verification before claiming completion**

Run:

```powershell
git status --short --branch
git log -4 --oneline
```

Expected: the new plan and implementation commits are visible; only the user's pre-existing untracked files remain. Do not push or deploy.
