# Gemini Files Cleanup Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gemini audio-file deletion tolerate bounded transient failures while preserving safe fail-closed transcription behavior.

**Architecture:** Keep retry ownership inside `GeminiAudioTranscriber` and apply it only to `client.files.delete()`. Inject a sleeper for deterministic offline tests, classify HTTP 404 as idempotent success, retry timeout/transport/429/5xx at most three attempts with 1-second and 2-second delays, and preserve existing primary-error precedence.

**Tech Stack:** Python 3.12+, Pydantic 2, `google-genai`, `httpx`, pytest, Typer, yt-dlp, FFmpeg, Astro, Vitest.

## Global Constraints

- Follow strict TDD: add one minimal failing behavior test, verify the expected RED, implement only enough for GREEN, then run the focused file.
- Retry only Gemini `files.delete()`; do not retry upload, generation, summarization, OpenAI calls, or the complete `add` workflow.
- Make at most three delete attempts with sleeps exactly `1.0` and `2.0` seconds after the first and second retryable failures.
- Treat Gemini HTTP 404 deletion as success; retry timeout, transport, HTTP 429, and Gemini 5xx failures; fail immediately for all other ordinary failures.
- Propagate `KeyboardInterrupt` and `SystemExit` immediately without sleeping or retrying.
- Preserve generation/validation failure as primary when cleanup also fails.
- Do not expose API keys, source URLs, transcripts, local paths, Gemini file names/URIs, prompts, raw SDK responses, or raw exception text.
- Do not add environment variables, CLI options, SDK-global retry settings, account-wide Files reconciliation, background work, or cross-provider fallback.
- Daily tests use fakes and local fixtures only; only the final explicitly approved acceptance may use YouTube, local media binaries, and Gemini API usage.
- Preserve the inaccessible pre-existing `.pytest-task2-basetemp/`; never delete or stage it.
- Do not push, create a PR, merge, or deploy.

---

## File Structure

- Modify `src/ai_digest/transcribers/gemini.py`: injected sleeper, delete retry loop, and cleanup-error classification.
- Modify `tests/test_gemini_transcriber.py`: deterministic delete-outcome fake and focused lifecycle/error tests.
- Modify `docs/superpowers/specs/2026-08-25-gemini-file-cleanup-retry-design.md`: record implemented/verified status only after evidence exists.
- Modify `progress.md`: actual RED/GREEN counts, complete gates, installed tool versions, live outcome, remote cleanup evidence, risks, and next step.
- Modify `todo.md`: check only work that actually passed; retain the overall two-case YouTube acceptance item unless both evidence sets exist.

---

### Task 1: Bounded Retry Mechanics for Transient Delete Failures

**Files:**
- Modify: `tests/test_gemini_transcriber.py`
- Modify: `src/ai_digest/transcribers/gemini.py`

**Interfaces:**
- Consumes: `GeminiAudioTranscriber(client: Any, model: str)` and `client.files.delete(name=str) -> None`.
- Produces: `GeminiAudioTranscriber(client: Any, model: str, sleeper: Callable[[float], None] = time.sleep)` and a private `_delete_uploaded(name: str) -> None` cleanup boundary.

- [ ] **Step 1: Extend the fake with ordered delete outcomes**

Replace `ControlledFiles.__init__` and `delete` with this backward-compatible form:

```python
class ControlledFiles(FakeFiles):
    def __init__(
        self,
        events: list[tuple[str, str]],
        *,
        upload_error: BaseException | None = None,
        delete_error: BaseException | None = None,
        delete_outcomes: list[BaseException | None] | None = None,
    ) -> None:
        super().__init__(events)
        self.upload_error = upload_error
        self.delete_error = delete_error
        self.delete_outcomes = iter(delete_outcomes or [])

    def upload(self, *, file: Path) -> object:
        if self.upload_error is not None:
            self.events.append(("upload", file.name))
            raise self.upload_error
        return super().upload(file=file)

    def delete(self, *, name: str) -> None:
        self.events.append(("delete", name))
        outcome = next(self.delete_outcomes, self.delete_error)
        if outcome is not None:
            raise outcome
```

This is test infrastructure only and must not change production behavior.

- [ ] **Step 2: Write the failing two-retries-then-success test**

Append:

```python
def test_cleanup_retries_transient_failures_with_bounded_delays(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(
            events,
            delete_outcomes=[
                httpx.TimeoutException("SECRET timeout"),
                errors.ServerError(503, {"message": "SECRET server"}, None),
                None,
            ],
        ),
        models=FakeModels(events, [SimpleNamespace(text="complete transcript")]),
    )

    result = GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
        [make_chunk(tmp_path, "chunk.mp3")]
    )

    assert result == "complete transcript"
    assert [event for event in events if event[0] == "delete"] == [
        ("delete", "files/chunk-1"),
        ("delete", "files/chunk-1"),
        ("delete", "files/chunk-1"),
    ]
    assert sleeps == [1.0, 2.0]
```

- [ ] **Step 3: Run the new test and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py::test_cleanup_retries_transient_failures_with_bounded_delays -v --basetemp .pytest-cleanup-retry-red
```

Expected: FAIL with `TypeError` because `GeminiAudioTranscriber.__init__()` does not accept `sleeper`.

- [ ] **Step 4: Implement the minimum bounded retry loop**

Add imports:

```python
import time
from collections.abc import Callable
```

Change the constructor and add the private method:

```python
    _CLEANUP_RETRY_DELAYS = (1.0, 2.0)

    def __init__(
        self,
        client: Any,
        model: str,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._model = model
        self._sleep = sleeper

    def _delete_uploaded(self, name: str) -> None:
        for attempt in range(len(self._CLEANUP_RETRY_DELAYS) + 1):
            try:
                self._client.files.delete(name=name)
                return
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as error:
                retryable = isinstance(
                    error,
                    (httpx.TimeoutException, httpx.TransportError, errors.ServerError),
                )
                if not retryable or attempt == len(self._CLEANUP_RETRY_DELAYS):
                    raise
                self._sleep(self._CLEANUP_RETRY_DELAYS[attempt])
```

Replace the direct cleanup call in `_transcribe_chunk`:

```python
                    self._delete_uploaded(uploaded.name)
```

- [ ] **Step 5: Run the focused test and verify GREEN**

Run the Step 3 command with basetemp `.pytest-cleanup-retry-green`.

Expected: 1 passed; `sleeps == [1.0, 2.0]` and exactly three delete events.

- [ ] **Step 6: Add the exhaustion regression test**

Append:

```python
def test_cleanup_stops_after_three_transient_failures(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(
            events,
            delete_outcomes=[httpx.TransportError("SECRET transport")] * 3,
        ),
        models=FakeModels(events, [SimpleNamespace(text="complete transcript")]),
    )

    with pytest.raises(DigestError) as raised:
        GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
            [make_chunk(tmp_path, "chunk.mp3")]
        )

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "TRANSCRIPTION_FAILED",
        "message": "Audio transcription cleanup failed",
        "retryable": False,
    }
    assert len([event for event in events if event[0] == "delete"]) == 3
    assert sleeps == [1.0, 2.0]
    assert "SECRET" not in rendered_exception(raised.value)
```

Run this test alone. Expected: PASS because Step 4 already established the bounded mechanic; this is a regression assertion for the upper bound, not a new implementation branch.

- [ ] **Step 7: Run the complete Gemini transcriber file**

```powershell
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py -v --basetemp .pytest-cleanup-retry-task1
```

Expected: all tests pass. Existing first-attempt success tests must still record exactly one delete and no delay.

- [ ] **Step 8: Commit Task 1**

```powershell
git add -- src/ai_digest/transcribers/gemini.py tests/test_gemini_transcriber.py
git diff --cached --check
git commit -m "fix: retry transient Gemini file cleanup"
```

---

### Task 2: HTTP Semantics, Error Precedence, and Interrupt Safety

**Files:**
- Modify: `tests/test_gemini_transcriber.py`
- Modify: `src/ai_digest/transcribers/gemini.py`

**Interfaces:**
- Consumes: `_delete_uploaded(name: str) -> None` from Task 1.
- Produces: idempotent HTTP 404 success and retryable HTTP 429 classification, without changing the existing public `DigestError` contract.

- [ ] **Step 1: Write the failing HTTP 404 idempotency test**

Append:

```python
def test_cleanup_treats_not_found_as_already_deleted(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(
            events,
            delete_outcomes=[errors.ClientError(404, {"message": "SECRET missing"}, None)],
        ),
        models=FakeModels(events, [SimpleNamespace(text="complete transcript")]),
    )

    result = GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
        [make_chunk(tmp_path, "chunk.mp3")]
    )

    assert result == "complete transcript"
    assert len([event for event in events if event[0] == "delete"]) == 1
    assert sleeps == []
```

- [ ] **Step 2: Run the 404 test and verify RED**

```powershell
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py::test_cleanup_treats_not_found_as_already_deleted -v --basetemp .pytest-cleanup-404-red
```

Expected: FAIL because the current cleanup loop propagates `ClientError(404)` and the adapter maps it to `Audio transcription cleanup failed`.

- [ ] **Step 3: Implement HTTP 404 as idempotent success**

Inside `_delete_uploaded`, immediately after the control-flow exception branch, add:

```python
            except errors.ClientError as error:
                if error.code == 404:
                    return
                raise
```

Keep the later ordinary-exception branch for timeout, transport, server, and unexpected failures. Because `ClientError` is handled first, it must not fall through to that branch.

- [ ] **Step 4: Run the 404 test and verify GREEN**

Run the Step 2 command with basetemp `.pytest-cleanup-404-green`.

Expected: 1 passed, one delete attempt, no sleep.

- [ ] **Step 5: Write the failing HTTP 429 retry test**

Append:

```python
def test_cleanup_retries_rate_limit_then_succeeds(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(
            events,
            delete_outcomes=[
                errors.ClientError(429, {"message": "SECRET limited"}, None),
                None,
            ],
        ),
        models=FakeModels(events, [SimpleNamespace(text="complete transcript")]),
    )

    result = GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
        [make_chunk(tmp_path, "chunk.mp3")]
    )

    assert result == "complete transcript"
    assert len([event for event in events if event[0] == "delete"]) == 2
    assert sleeps == [1.0]
```

Run:

```powershell
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py::test_cleanup_retries_rate_limit_then_succeeds -v --basetemp .pytest-cleanup-429-red
```

Expected: FAIL because the 404-only `ClientError` branch still treats 429 as non-retryable and returns the safe cleanup error.

- [ ] **Step 6: Implement HTTP 429 as retryable**

Replace the 404-only `ClientError` branch with:

```python
            except errors.ClientError as error:
                if error.code == 404:
                    return
                if error.code != 429 or attempt == len(self._CLEANUP_RETRY_DELAYS):
                    raise
                self._sleep(self._CLEANUP_RETRY_DELAYS[attempt])
```

Run the Step 5 command with basetemp `.pytest-cleanup-429-green`.

Expected: 1 passed, two delete attempts, and `sleeps == [1.0]`.

- [ ] **Step 7: Verify non-retryable, precedence, and interruption contracts**

Enhance existing tests with these assertions:

```python
# test_cleanup_failure_after_success_is_safe_and_non_retryable
assert len([event for event in events if event[0] == "delete"]) == 1

# test_primary_failure_wins_when_generation_and_cleanup_both_fail
assert len([event for event in events if event[0] == "delete"]) == 1

# test_cleanup_interrupt_propagates
assert len([event for event in events if event[0] == "delete"]) == 1
```

Add a transient dual-failure test:

```python
def test_primary_generation_failure_wins_after_cleanup_retries_exhausted(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(
            events,
            delete_outcomes=[errors.ServerError(503, {"message": "SECRET cleanup"}, None)] * 3,
        ),
        models=FakeModels(events, [httpx.TimeoutException("SECRET generation")]),
    )

    with pytest.raises(DigestError) as raised:
        GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
            [make_chunk(tmp_path, "chunk.mp3")]
        )

    assert (raised.value.code, raised.value.retryable) == ("TRANSCRIPTION_TIMEOUT", True)
    assert len([event for event in events if event[0] == "delete"]) == 3
    assert sleeps == [1.0, 2.0]
    assert "SECRET" not in rendered_exception(raised.value)
```

These assertions exercise existing guarantees around the newly added retry branch; they require no additional production behavior beyond Steps 3 and Task 1.

- [ ] **Step 8: Run focused and related suites**

```powershell
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py -v --basetemp .pytest-cleanup-retry-task2
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py tests/test_openai_transcriber.py tests/test_youtube_extractor.py tests/test_cli.py --basetemp .pytest-cleanup-retry-related
```

Expected: all tests pass; no test performs real sleeps, network, media, or API calls.

- [ ] **Step 9: Commit Task 2**

```powershell
git add -- src/ai_digest/transcribers/gemini.py tests/test_gemini_transcriber.py
git diff --cached --check
git commit -m "test: secure Gemini cleanup retry semantics"
```

---

### Task 3: Complete Verification, Live Acceptance, and Progress Evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-08-25-gemini-file-cleanup-retry-design.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: verified bounded cleanup behavior from Tasks 1–2 and the approved public no-caption URL.
- Produces: evidence-backed implementation status and a clean isolated acceptance result, or an explicit unverified/blocking record.

- [ ] **Step 1: Run the complete Python suite with an absent workspace basetemp**

```powershell
$testRoot = Join-Path (Resolve-Path '.').Path '.pytest-cleanup-retry-full'
if (Test-Path -LiteralPath $testRoot) { throw 'Refusing to overwrite existing test directory' }
$env:PYTHONPATH = Join-Path (Resolve-Path '.').Path 'src'
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest --basetemp $testRoot
```

Expected: all tests pass. Record the exact count and warnings. Delete only this exact test root after verifying it resolves beneath the current worktree.

- [ ] **Step 2: Run frontend, build, Schema, deployment, diff, and media gates**

```powershell
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' -m pytest tests/test_domain.py tests/test_storage.py -v --basetemp .pytest-cleanup-retry-schema
Push-Location site
npm.cmd test
npm.cmd run build
Pop-Location
git diff --check
& 'D:\Project\AI-Summary\.venv\Scripts\python.exe' scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
Get-ChildItem -LiteralPath site/dist -Recurse -File |
    Where-Object { $_.Extension -in '.mp3','.m4a','.webm','.vtt','.srt' }
```

Expected: Schema/storage pass; Vitest passes; Astro reports zero diagnostics and builds all routes; diff and deployment verifier exit 0; media scan prints nothing.

- [ ] **Step 3: Confirm live prerequisites without printing secrets**

Refresh machine/user PATH and explicitly prepend the discovered yt-dlp package directory when necessary. Run:

```powershell
yt-dlp --version
ffmpeg -version | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'GEMINI_API_KEY is unset' }
```

Expected: `yt-dlp 2026.08.19`, `FFmpeg 9.0.1`, and a silent successful key check. If any prerequisite fails, stop and record the blocker without starting acceptance.

- [ ] **Step 4: Run exactly one approved live acceptance in a new isolated directory**

```powershell
$acceptanceRoot = 'D:\Project\AI-Summary\.youtube-acceptance-gemini-retry'
if (Test-Path -LiteralPath $acceptanceRoot) { throw 'Acceptance directory already exists' }
$env:PYTHONPATH = 'D:\Project\AI-Summary\.worktrees\provider-aligned-transcription\src'
$env:AI_DIGEST_PROVIDER = 'gemini'
$env:AI_DIGEST_SUMMARY_ROOT = $acceptanceRoot
& 'D:\Project\AI-Summary\.venv\Scripts\ai-digest.exe' add 'https://www.youtube.com/watch?v=4gciWspBVHw'
```

Expected: exit 0 and structured stages ending in `complete`. This command may incur Gemini API usage. Do not run it a second time after any failure without a new decision.

- [ ] **Step 5: Validate the live record without exposing sensitive fields**

Use `SummaryRecord.model_validate_json` and assert:

```python
files = list(acceptance_root.glob("*.json"))
assert len(files) == 1
raw = files[0].read_text(encoding="utf-8")
record = SummaryRecord.model_validate_json(raw)
assert record.source_type == "youtube"
assert str(record.canonical_url) == "https://www.youtube.com/watch?v=4gciWspBVHw"
assert record.status == "published"
assert record.summary.strip()
assert record.editorial.strip()
assert 3 <= len(record.key_points) <= 5
for forbidden in (
    str(repository_root),
    ".mp3",
    ".m4a",
    ".webm",
    ".vtt",
    ".srt",
    "files/",
    "gemini://",
):
    assert forbidden.lower() not in raw.lower()
```

Do not print the record, transcript, generated ID, full local path, Gemini file metadata, or raw JSON.

- [ ] **Step 6: Verify cleanup and remove only the isolated local record**

Confirm no media file exists beneath the repository. For remote cleanup, do not list or delete unrelated account Files. Compare only the pre-run and post-run non-identifying counts needed to establish that the acceptance created no residual File. If cleanup failed, stop and preserve safe counts/timestamps; do not retry the paid acceptance.

After successful validation, resolve the exact acceptance root, verify it equals `D:\Project\AI-Summary\.youtube-acceptance-gemini-retry`, delete only that directory, and confirm it no longer exists.

- [ ] **Step 7: Update documentation with actual evidence**

Set the design status to `Implemented and verified` only if automated tests and the live no-caption acceptance both pass. Otherwise set it to `Implemented; live acceptance blocked` and record the exact safe failure.

In `progress.md`, record exact test/build counts, tool versions, model, approved URL, CLI outcome, JSON validation, local/remote cleanup evidence, warnings, risks, and next step.

In `todo.md`, check the cleanup-retry implementation only after automated gates pass. Keep the combined captioned/no-caption acceptance unchecked unless both cases have valid recorded evidence.

- [ ] **Step 8: Re-run all gates after documentation changes**

Repeat Steps 1–2 with fresh absent basetemp names. Expected: the same or higher passing counts, zero build diagnostics, deployment verifier exit 0, `git diff --check` exit 0, and no media files.

- [ ] **Step 9: Review scope and commit Task 3**

```powershell
git status --short
git diff --name-only
git diff --check
git add -- docs/superpowers/specs/2026-08-25-gemini-file-cleanup-retry-design.md progress.md todo.md
git diff --cached --name-only
git commit -m "docs: verify Gemini cleanup retry acceptance"
```

Expected staged paths: only the design, `progress.md`, and `todo.md`. Do not stage acceptance JSON, `site/dist`, test temp directories, proposal documents, or the pre-existing inaccessible pytest directory.

---

## Final Review Gate

- Map every requirement in `docs/superpowers/specs/2026-08-25-gemini-file-cleanup-retry-design.md` to Tasks 1–3.
- Confirm only delete is retried and delays are exactly 1.0 and 2.0 seconds.
- Confirm 404 succeeds, timeout/transport/429/5xx retry, other failures stop, and interruptions propagate.
- Confirm generation failure remains primary when cleanup also exhausts retries.
- Confirm automated tests contain no real sleep, network, media binary, or API dependency.
- Confirm no secret, transcript, source URL, local path, Gemini name/URI, prompt, raw SDK response, or raw exception appears in public errors.
- Confirm live acceptance ran at most once during Task 3 and any remote File created by it is absent.
- Confirm the worktree contains only intentional changes and `.pytest-task2-basetemp/` remains untouched.
- Do not invoke branch finishing while the combined captioned/no-caption acceptance remains incomplete.
