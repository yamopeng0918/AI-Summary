# One-Command Summary Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `python scripts/publish_url.py '<public-url>'` to create or resume one summary, run all local gates, publish exactly that JSON, wait for Pages, and verify the public routes.

**Architecture:** Put the testable publishing state machine in `src/ai_digest/publishing.py`; keep `scripts/publish_url.py` as thin production composition and argument/error handling. Inject command execution, summary creation, HTTP reads, sleeping, and time so automated tests never call GitHub, npm, Git, or a provider.

**Tech Stack:** Python 3.12+, Pydantic domain models, subprocess, urllib, pytest, GitHub Actions REST API

## Global Constraints

- Invocation is exactly `python scripts/publish_url.py '<URL>'`.
- Run only from repository root on `master`; ignore unrelated untracked files but reject tracked or staged changes.
- Never stage with `git add .`, merge, reset, delete content, force-push, or expose credentials.
- Preserve an uncommitted summary JSON after any downstream failure and resume it without a second provider call.
- Automated tests use injected fakes and require no network, provider key, npm, or Git repository mutation.
- Public defaults are `yamopeng0918/AI-Summary`, `Deploy to GitHub Pages`, and `https://yamopeng0918.github.io/AI-Summary/`.

---

### Task 1: Model publishing errors and Git preflight

**Files:**
- Create: `src/ai_digest/publishing.py`
- Create: `tests/test_publishing.py`

**Interfaces:**
- Produce `PublishError(stage: str, message: str)`.
- Produce `CommandResult(returncode: int, stdout: str = "", stderr: str = "")`.
- Produce `CommandRunner = Callable[[Sequence[str], Path], CommandResult]`.
- Produce `PublishingConfig(repository_root: Path, summary_root: Path, site_root: str, github_repository: str, workflow_name: str, poll_attempts: int = 30, poll_delay_seconds: float = 10)`.
- Produce `SummaryPublisher.preflight() -> None`.

- [ ] **Step 1: Write failing tests for root, branch, dirty tracked files, and remote state**

Use a recording fake runner. Assert `preflight()` executes, in order:

```python
["git", "rev-parse", "--show-toplevel"]
["git", "branch", "--show-current"]
["git", "status", "--porcelain", "--untracked-files=no"]
["git", "fetch", "origin", "master"]
["git", "rev-list", "--left-right", "--count", "master...origin/master"]
```

Require exact root, branch `master`, empty tracked status, and counts `0\t0`. Assert a `PublishError` with stage `preflight` for each mismatch and that later commands are not called.

- [ ] **Step 2: Run RED**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_publishing.py -v
```

Expected: import failure because `ai_digest.publishing` does not exist.

- [ ] **Step 3: Implement the minimal dataclasses, error, injected runner, and `preflight()`**

`SummaryPublisher` receives `config`, `repository`, `add_summary`, `run_command`, `fetch_json`, `fetch_text`, `sleep`, and `now`. A private `_run_checked(command, stage, cwd)` raises `PublishError` using a concise sanitized stderr message when return code is non-zero.

- [ ] **Step 4: Run focused tests and commit**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_publishing.py -v
git add src/ai_digest/publishing.py tests/test_publishing.py
git commit -m "feat: add publishing preflight"
```

### Task 2: Create or resume one summary safely

**Files:**
- Modify: `src/ai_digest/publishing.py`
- Modify: `tests/test_publishing.py`

**Interfaces:**
- Produce `SummaryPublisher.resolve_summary(raw_url: str) -> tuple[SummaryRecord, Path, bool]`, where the boolean is true only for a newly created record.
- Consume `normalize_public_url`, `SummaryRepository.list()`, and injected `add_summary(raw_url) -> SummaryRecord`.

- [ ] **Step 1: Add RED tests**

Cover:

- no canonical match calls `add_summary` once and returns `data/summaries/<id>.json`;
- canonical match returns the existing record without calling the provider;
- multiple canonical matches raise `PublishError("summary", ...)`;
- a matching record whose file is absent raises instead of guessing;
- invalid public URL is mapped to a safe publishing error.

- [ ] **Step 2: Implement the minimal resolver and run tests**

Normalize once, compare `str(record.canonical_url)`, and require the resolved path to be directly under `summary_root`.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_publishing.py -v
```

- [ ] **Step 3: Commit**

```powershell
git add src/ai_digest/publishing.py tests/test_publishing.py
git commit -m "feat: resume retained summary publication"
```

### Task 3: Run gates and publish exactly one JSON

**Files:**
- Modify: `src/ai_digest/publishing.py`
- Modify: `tests/test_publishing.py`

**Interfaces:**
- Produce `SummaryPublisher.run_gates() -> None`.
- Produce `SummaryPublisher.commit_and_push(record: SummaryRecord, path: Path) -> str`, returning the full pushed commit SHA.

- [ ] **Step 1: Add RED gate-order and failure tests**

Assert exact commands and working directories:

```python
[sys.executable, "-m", "pytest"]                         # repository root
["npm.cmd" or "npm", "test"]                           # site/
["npm.cmd" or "npm", "run", "build:pages"]            # site/
[sys.executable, "scripts/verify_deployment.py", "--tracked", "--dist", "site/dist", "--base", "/AI-Summary/"]
```

Any non-zero command stops subsequent commands and raises with the correct stage.

- [ ] **Step 2: Add RED exact-staging tests**

Assert `commit_and_push()`:

1. checks whether the summary path is already in `HEAD` with `git cat-file -e HEAD:<path>`;
2. for an uncommitted file, runs `git add -- <path>`;
3. checks `git diff --cached --name-only -z` and requires exactly the UTF-8 path;
4. commits `content: publish <id>`;
5. resolves `git rev-parse HEAD`;
6. pushes `git push origin master`.

If the file is already in HEAD, do not stage or create an empty commit; return the commit from `git log -1 --format=%H -- <path>` and require local HEAD to be pushed.

- [ ] **Step 3: Implement minimal gates/staging/push and run tests**

Use `-z` binary-safe semantics for staged paths through a dedicated bytes-capable runner result, or invoke `git diff --cached --name-only -- <path>` with `core.quotepath=false` and explicit UTF-8 decoding. Prefer the same NUL/bytes pattern as `verify_deployment.py`.

- [ ] **Step 4: Run focused/full tests and commit**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_publishing.py -v
& '.\.venv\Scripts\python.exe' -m pytest
git add src/ai_digest/publishing.py tests/test_publishing.py
git commit -m "feat: validate and push one summary"
```

### Task 4: Wait for Pages and verify public routes

**Files:**
- Modify: `src/ai_digest/publishing.py`
- Modify: `tests/test_publishing.py`

**Interfaces:**
- Produce `SummaryPublisher.wait_for_workflow(commit_sha: str) -> str`, returning the run URL.
- Produce `SummaryPublisher.verify_public(record_id: str) -> None`.
- Produce `SummaryPublisher.publish(raw_url: str) -> PublishResult` with record ID, commit SHA, workflow URL, and detail URL.

- [ ] **Step 1: Add workflow RED tests**

Fake GitHub JSON responses for not-found, queued, in-progress, success, failure, and timeout. Match both `head_sha == commit_sha` and `name == config.workflow_name`; do not accept another commit's successful run.

- [ ] **Step 2: Add public verification RED tests**

Assert the homepage request includes a cache-busting `verify=<timestamp>` query and contains the exact record ID. Assert the detail URL uses `urllib.parse.quote(record_id, safe="")` and that fetch failure or non-200 response becomes `PublishError("public", ...)`.

- [ ] **Step 3: Implement bounded polling and public checks**

Use the public endpoint:

```text
https://api.github.com/repos/{owner}/{repo}/actions/runs?head_sha={sha}&per_page=20
```

Sleep only between incomplete attempts. Never re-run or cancel workflows.

- [ ] **Step 4: Add end-to-end state-machine tests and commit**

Cover new summary success, retained JSON resume, already-pushed resume, gate failure, push failure, workflow failure, and public failure. Verify no provider call on either resume path.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_publishing.py -v
git add src/ai_digest/publishing.py tests/test_publishing.py
git commit -m "feat: verify published summary deployment"
```

### Task 5: Add the executable script and documentation

**Files:**
- Create: `scripts/publish_url.py`
- Create: `tests/test_publish_url_script.py`
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- `scripts.publish_url.main(argv: Sequence[str] | None = None) -> int`.
- Production composition uses `SummaryRepository(Path("data/summaries"))`, `cli._workflow(...).run(url, cli._now())`, subprocess without `shell=True`, urllib requests with a fixed user agent, and the approved GitHub/site defaults.

- [ ] **Step 1: Add CLI RED tests**

Cover exactly one positional URL, help/usage failure, success output containing ID/commit/workflow/detail URL, `PublishError` safe stderr and exit 1, and `DigestError` safe stderr and exit 1. Assert URL/key values are not echoed in errors.

- [ ] **Step 2: Implement the thin script**

Do not activate a virtual environment or mutate execution policy. Document both:

```powershell
& '.\.venv\Scripts\python.exe' scripts/publish_url.py 'https://example.com/public-article'
```

and, when the venv is already active:

```powershell
python scripts/publish_url.py 'https://example.com/public-article'
```

- [ ] **Step 3: Run every local completion gate**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest
Set-Location site
npm.cmd test
npm.cmd run build:pages
Set-Location ..
& '.\.venv\Scripts\python.exe' scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
```

- [ ] **Step 4: Perform one user-approved end-to-end acceptance**

Use a new directly readable public article URL supplied or explicitly approved by the user. Do not reuse an already-published URL as the only acceptance for the creation path. Confirm the new workflow succeeds and the public homepage/detail page contain the new record.

- [ ] **Step 5: Update progress records and commit**

Record commands, test counts, workflow run, commit, public URLs, and any warnings. Check only verified todo items.

```powershell
git add scripts/publish_url.py tests/test_publish_url_script.py README.md progress.md todo.md
git commit -m "feat: add one-command summary publishing"
```
