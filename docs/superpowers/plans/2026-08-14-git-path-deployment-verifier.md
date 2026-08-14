# Git Path Deployment Verifier Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tracked-file deployment verification reliable for Chinese and other non-ASCII Git paths, then restore the blocked Pages deployment.

**Architecture:** Introduce one focused helper that obtains tracked paths through `git ls-files -z` as bytes and decodes each NUL-delimited path independently with UTF-8 `surrogateescape`. `main()` continues to pass `Path` objects to the unchanged sensitive-file scanner.

**Tech Stack:** Python 3.12+, subprocess, pathlib, pytest, GitHub Actions

## Global Constraints

- Preserve `--tracked`, `--dist`, `--base`, sensitive patterns, and exit-code behavior.
- Do not change summary JSON or rename the Chinese summary ID.
- Use TDD and local fixtures/mocks; automated tests require no network.
- Do not deploy until focused tests, full Python suite, real verifier, and `git diff --check` pass.

---

### Task 1: Parse tracked Git paths without quoting or locale decoding

**Files:**
- Modify: `tests/test_verify_deployment.py`
- Modify: `scripts/verify_deployment.py`

**Interfaces:**
- Produces: `tracked_paths() -> list[Path]`.
- Consumes: `subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)`.

- [ ] **Step 1: Add a failing Chinese-path test**

Mock `subprocess.run` to return `stdout="data/summaries/中文摘要.json\0".encode("utf-8")`, call `tracked_paths()`, and expect `[Path("data/summaries/中文摘要.json")]` plus the exact `git ls-files -z` invocation with no text decoding.

- [ ] **Step 2: Verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_verify_deployment.py::test_tracked_paths_supports_utf8_filenames -v
```

Expected: collection/import failure because `tracked_paths` does not exist.

- [ ] **Step 3: Implement the minimal helper**

```python
def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        Path(raw_path.decode("utf-8", errors="surrogateescape"))
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]
```

Replace the current text-mode `git ls-files` block in `main()` with `scan_sensitive_files(tracked_paths())`.

- [ ] **Step 4: Add Git failure coverage**

Mock `subprocess.run` to raise `subprocess.CalledProcessError(128, ["git", "ls-files", "-z"], stderr=b"fatal: UTF-8 path")` and assert `tracked_paths()` propagates that Git failure without attempting locale text decoding.

- [ ] **Step 5: Verify GREEN and regression safety**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_verify_deployment.py -v
& '.\.venv\Scripts\python.exe' -m pytest
& '.\.venv\Scripts\python.exe' scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
```

Expected: all commands exit 0; the real verifier scans the tracked Chinese JSON.

- [ ] **Step 6: Commit**

```powershell
git add scripts/verify_deployment.py tests/test_verify_deployment.py docs/superpowers/plans/2026-08-14-git-path-deployment-verifier.md
git commit -m "fix: support Unicode paths in deployment verifier"
```

### Task 2: Restore and verify Pages deployment

**Files:**
- Modify: `progress.md`
- Modify: `todo.md` only if an existing deployment-verification item accurately becomes complete.

**Interfaces:**
- Consumes: GitHub Actions workflow triggered by `master` push.
- Produces: successful workflow for the fix commit and a public page containing `20260814-python爬蟲新手筆記-pala-tw-8ed66e81`.

- [ ] **Step 1: Merge the verified branch into `master` and rerun the full Python suite on the merge result.**
- [ ] **Step 2: Run the tracked/dist deployment verifier and sensitive-data gate on `master`.**
- [ ] **Step 3: Push `master` to `origin`.**
- [ ] **Step 4: Poll the new workflow until completion; require `conclusion=success`.**
- [ ] **Step 5: Request the public homepage with cache bypass and confirm the new summary ID; request its detail URL and require HTTP 200.**
- [ ] **Step 6: Record the failed run, root cause, fix commit, successful run, and public smoke evidence in `progress.md`; verify and commit the documentation update.**

