# Windows CLI UTF-8 Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ai-digest list` and `ai-digest show` display complete Unicode content in Windows interactive terminals without requiring `PYTHONUTF8=1`, while preserving redirected and non-Windows output behavior.

**Architecture:** Add one narrow stream-configuration helper and a callable console-script entry point in the existing CLI module. The entry point configures only Windows TTY stdout/stderr as UTF-8 before invoking the unchanged Typer application; repositories, records, command formats, redirected streams, and non-Windows platforms remain untouched.

**Tech Stack:** Python 3.12+, Typer/Click, pytest, setuptools console scripts.

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-29-windows-cli-utf8-design.md` and repository `AGENTS.md`.
- Use strict Red-Green-Refactor: no production change before its focused test fails for the expected missing behavior.
- Configure only Windows interactive TTY stdout/stderr; do not modify pipes, redirected files, non-Windows streams, the global Windows code page, PowerShell profiles, or user environment variables.
- Preserve `list` tab-separated fields, `show` JSON shape, and all existing ASCII-safe event/error payloads.
- Do not use `errors="ignore"`, replacement text, or ASCII escaping to hide unsupported content.
- Do not access network services, provider credentials, or paid APIs.
- Preserve all unrelated tracked and untracked user changes. Do not push or deploy without explicit user authorization.

---

## File Structure

- Modify `src/ai_digest/cli.py`: own Windows TTY stream configuration and the console-script entry point; keep command behavior in the existing Typer app.
- Modify `tests/test_cli.py`: cover platform/TTY/reconfiguration boundaries, safe unsupported streams, entry-point ordering, and Unicode `list`/`show` behavior.
- Modify `pyproject.toml`: point the `ai-digest` console script at the new callable entry point.
- Modify `README.md`: remove the CP950 workaround as a requirement and document automatic Windows interactive UTF-8 setup plus unchanged redirection behavior.
- Modify `progress.md` and `todo.md`: record only verified implementation evidence and update the next step.

### Task 1: Windows TTY Configuration Boundary and Console Entry Point

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_digest/cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: existing module-level `app: typer.Typer` and Python text streams exposing `isatty()` and optionally `reconfigure()`.
- Produces: `_configure_windows_utf8(stream: TextIO, *, platform: str) -> None` and `main() -> None`; setuptools console script `ai-digest = "ai_digest.cli:main"`.

- [ ] **Step 1: Add fake stream fixtures and the first failing Windows TTY test**

Add `import sys` and `from typing import TextIO` only where required by the final production signature. In `tests/test_cli.py`, add a minimal recording stream:

```python
class RecordingTextStream:
    def __init__(self, *, tty: bool, supports_reconfigure: bool = True) -> None:
        self.tty = tty
        self.encoding = "cp950"
        self.reconfigure_calls: list[dict[str, str]] = []
        if not supports_reconfigure:
            self.reconfigure = None  # type: ignore[assignment]

    def isatty(self) -> bool:
        return self.tty

    def reconfigure(self, **kwargs: str) -> None:
        self.reconfigure_calls.append(kwargs)
        self.encoding = kwargs["encoding"]
```

Add the first behavior test:

```python
def test_windows_interactive_stream_is_reconfigured_to_utf8() -> None:
    stream = RecordingTextStream(tty=True)

    cli._configure_windows_utf8(stream, platform="win32")

    assert stream.encoding == "utf-8"
    assert stream.reconfigure_calls == [{"encoding": "utf-8"}]
```

- [ ] **Step 2: Run the first test and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py::test_windows_interactive_stream_is_reconfigured_to_utf8 -q
```

Expected: FAIL because `ai_digest.cli` has no attribute `_configure_windows_utf8`; no production code has changed yet.

- [ ] **Step 3: Add the remaining failing boundary tests before implementation**

Add tests with explicit assertions:

```python
def test_non_windows_stream_is_not_reconfigured() -> None:
    stream = RecordingTextStream(tty=True)

    cli._configure_windows_utf8(stream, platform="linux")

    assert stream.encoding == "cp950"
    assert stream.reconfigure_calls == []


def test_redirected_windows_stream_is_not_reconfigured() -> None:
    stream = RecordingTextStream(tty=False)

    cli._configure_windows_utf8(stream, platform="win32")

    assert stream.encoding == "cp950"
    assert stream.reconfigure_calls == []


def test_windows_tty_without_reconfigure_is_ignored() -> None:
    stream = RecordingTextStream(tty=True, supports_reconfigure=False)

    cli._configure_windows_utf8(stream, platform="win32")

    assert stream.encoding == "cp950"


def test_windows_tty_with_uninspectable_state_is_ignored() -> None:
    class UninspectableStream:
        def isatty(self) -> bool:
            raise OSError("stream closed")

    cli._configure_windows_utf8(UninspectableStream(), platform="win32")  # type: ignore[arg-type]
```

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py -k "windows_interactive_stream or non_windows_stream or redirected_windows_stream or without_reconfigure or uninspectable_state" -q
```

Expected: all new tests FAIL because the helper is absent.

- [ ] **Step 4: Implement the minimal stream helper**

In `src/ai_digest/cli.py`, import `sys` and `TextIO`, then add immediately before `create_app`:

```python
def _configure_windows_utf8(stream: TextIO, *, platform: str) -> None:
    if platform != "win32":
        return
    try:
        if not stream.isatty():
            return
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            return
        reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        return
```

Do not catch `UnicodeEncodeError` from commands and do not change `_emit`, `list_records`, or `show`.

- [ ] **Step 5: Run the boundary tests and verify GREEN**

Run the Step 3 focused command again.

Expected: all selected tests PASS.

- [ ] **Step 6: Write failing entry-point ordering and Unicode command tests**

Add an entry-point test:

```python
def test_main_configures_both_streams_before_invoking_app(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    stdout = object()
    stderr = object()
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(
        cli,
        "_configure_windows_utf8",
        lambda stream, *, platform: events.append(("configure", stream, platform)),
    )
    monkeypatch.setattr(cli, "app", lambda: events.append(("app",)))

    cli.main()

    assert events == [
        ("configure", stdout, "win32"),
        ("configure", stderr, "win32"),
        ("app",),
    ]
```

Add a real-command regression using a record whose title includes CP950-unrepresentable `级`:

```python
def test_list_and_show_preserve_unicode_after_windows_tty_configuration(
    tmp_path, monkeypatch
) -> None:
    record = make_record().model_copy(update={"title": "Unicode 级 title"})
    app, repository = make_app(tmp_path, FakeWorkflow(record))
    repository.save(record)
    console = RecordingTextStream(tty=True)
    emitted: list[str] = []
    cli._configure_windows_utf8(console, platform="win32")

    def encoded_echo(message: str, *, err: bool = False) -> None:
        str(message).encode(console.encoding)
        emitted.append(str(message))

    monkeypatch.setattr(cli.typer, "echo", encoded_echo)
    runner = CliRunner()

    listed = runner.invoke(app, ["list"])
    shown = runner.invoke(app, ["show", record.id])

    assert listed.exit_code == 0
    assert shown.exit_code == 0
    assert "Unicode 级 title" in emitted[0]
    assert json.loads(emitted[1])["title"] == "Unicode 级 title"
```

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py -k "main_configures_both_streams or preserve_unicode_after_windows_tty" -q
```

Expected: entry-point test FAIL because `main` is absent; the Unicode test passes only after the helper from Step 4 is present and proves no content is escaped or dropped.

- [ ] **Step 7: Implement the console entry point and package mapping**

Append to `src/ai_digest/cli.py` after `app = create_app(...)`:

```python
def main() -> None:
    _configure_windows_utf8(sys.stdout, platform=sys.platform)
    _configure_windows_utf8(sys.stderr, platform=sys.platform)
    app()
```

In `pyproject.toml`, replace only the console-script target:

```toml
[project.scripts]
ai-digest = "ai_digest.cli:main"
```

- [ ] **Step 8: Verify GREEN for the entry point and complete CLI file**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py -q
```

Expected: every `tests/test_cli.py` test passes with no failures; the two new entry-point tests pass.

- [ ] **Step 9: Reinstall the editable console script and perform a local process smoke test**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -e . --no-deps
$env:AI_DIGEST_SUMMARY_ROOT = (Resolve-Path 'data\summaries').Path
& '.\.venv\Scripts\ai-digest.exe' list
& '.\.venv\Scripts\ai-digest.exe' show '20260826-codex-app-保姆级全攻略-海量实战教程-一期精通codex-7cf4a92c'
```

Expected: install exits 0; both commands exit 0 without setting `PYTHONUTF8`; `list` displays the Unicode title and `show` emits JSON parseable by Python. Do not print environment variables or credentials.

- [ ] **Step 10: Commit Task 1**

Run:

```powershell
git diff --check
git add -- tests/test_cli.py src/ai_digest/cli.py pyproject.toml
git commit -m "fix: enable UTF-8 Windows CLI output"
```

Expected: one focused commit containing only the CLI implementation, package entry-point change, and tests.

### Task 2: Documentation, Full Verification, and Progress Record

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: verified `main() -> None` and `_configure_windows_utf8(stream: TextIO, *, platform: str) -> None` from Task 1.
- Produces: user-facing Windows behavior documentation and verified project status; no new runtime interface.

- [ ] **Step 1: Update Windows CLI documentation**

In `README.md`, after the direct virtual-environment executable example, add:

```markdown
在 Windows 互動式 PowerShell／Windows Terminal 中，`ai-digest` 會在啟動時將 stdout 與 stderr 設為 UTF-8，因此 `list` 與 `show` 可直接顯示繁體、簡體及其他 Unicode 內容，不必另外設定 `PYTHONUTF8=1`。輸出重新導向至檔案或 pipe 時，CLI 不會強制改寫串流編碼。
```

Do not tell users to change the global code page, execution policy, profile, or persistent environment.

- [ ] **Step 2: Run documentation consistency checks**

Run:

```powershell
rg -n "PYTHONUTF8|CP950|UTF-8|list|show" README.md progress.md todo.md docs/superpowers/specs/2026-08-29-windows-cli-utf8-design.md
```

Expected: README describes automatic Windows interactive UTF-8 setup; `progress.md` contains no statement that CP950 remains an unresolved risk after implementation; historical entries remain explicitly historical rather than silently deleted.

- [ ] **Step 3: Run the complete Python suite**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest
```

Expected: all tests pass; the two existing symlink tests may remain skipped on Windows when the account lacks symlink permission, and the existing third-party `google-genai` deprecation warning may remain. Record exact counts rather than copying prior counts.

- [ ] **Step 4: Run deployment safety and formatting gates**

Run:

```powershell
& '.\.venv\Scripts\python.exe' scripts\verify_deployment.py --tracked
git diff --check
git status --short
```

Expected: verifier exit 0; `git diff --check` has no errors; status contains only Task 2 files plus pre-existing unrelated untracked user files.

- [ ] **Step 5: Update project status from actual evidence**

In `progress.md`:

- replace the active CP950 risk with the verified automatic Windows interactive UTF-8 behavior;
- add the Task 1 commit, focused CLI test result, full Python result, smoke-test result, safety verifier result, and any genuine limitations;
- set the next step to the remaining `build-site`/local editing decision only after the Unicode task is verified.

In `todo.md`:

- mark the Windows CP950 TDD implementation item complete only if Steps 3 and 4 passed;
- keep unrelated and optional items unchanged.

- [ ] **Step 6: Re-run final evidence checks after documentation edits**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py -q
& '.\.venv\Scripts\python.exe' scripts\verify_deployment.py --tracked
git diff --check
git diff --name-only HEAD
```

Expected: CLI tests pass; verifier and diff check exit 0; the Task 2 diff contains exactly `README.md`, `progress.md`, and `todo.md`.

- [ ] **Step 7: Commit Task 2 without pushing**

Run:

```powershell
git add -- README.md progress.md todo.md
git commit -m "docs: record Windows CLI UTF-8 support"
git status --short --branch
```

Expected: a focused documentation commit; local branch is ahead of `origin/master`; pre-existing untracked user files remain untouched. Do not push, create a PR, or deploy without explicit user authorization.
