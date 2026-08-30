# Local Summary Editing and Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe local JSON editing and paid source-based regeneration for an existing AI Digest summary while preserving system fields and never corrupting the original record on failure.

**Architecture:** Keep creation, editing, regeneration, and persistence as separate responsibilities. Add `SummaryRepository.replace()` as the only validated atomic overwrite boundary, an isolated `EditorRunner`, and dedicated edit/regenerate workflows; the Typer CLI only composes dependencies and emits existing structured events.

**Tech Stack:** Python 3.12+, Pydantic 2, Typer, pathlib/tempfile/subprocess/shlex, pytest.

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-30-local-edit-regenerate-design.md` and `docs/superpowers/specs/2026-08-09-ai-digest-mvp-design.md`.
- Use TDD for every behavior: add one minimal test, run it and observe the expected failure, then add only the implementation required to pass.
- Preserve `schemaVersion`, `id`, `canonicalUrl`, `sourceType`, and `createdAt` during manual editing; set `updatedAt` from an aware Asia/Taipei clock.
- Regeneration preserves `id`, `createdAt`, and `status`, but refreshes source fields, generated content, classification, and `updatedAt`.
- `edit` is key-free. `regenerate` uses only the explicitly selected provider and performs no automatic fallback.
- External editors, networks, and paid APIs must be replaced by injected test doubles in automated tests.
- All writes pass through `SummaryRecord` validation and an atomic repository operation.
- Never include credentials, edited JSON contents, temporary paths containing sensitive data, or upstream exception text in public errors.

---

## File Map

- Modify `src/ai_digest/storage.py`: validated atomic replacement of an existing record.
- Create `src/ai_digest/editing.py`: editor command selection/execution and manual edit workflow.
- Create `src/ai_digest/regeneration.py`: source-based regeneration workflow.
- Modify `src/ai_digest/cli.py`: dependency composition and `edit`/`regenerate` commands.
- Modify `tests/test_storage.py`: replacement persistence contract.
- Create `tests/test_editing.py`: editor runner and edit workflow behavior.
- Create `tests/test_regeneration.py`: regeneration orchestration and invariants.
- Modify `tests/test_cli.py`: command wiring, events, key boundaries, and production composition.
- Modify `README.md`, `progress.md`, and `todo.md`: operation guide and verified project status.

### Task 1: Validated Atomic Repository Replacement

**Files:**
- Modify: `src/ai_digest/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `SummaryRepository.get(record_id: str) -> SummaryRecord`, `_write(destination: Path, record: SummaryRecord) -> None`.
- Produces: `SummaryRepository.replace(record_id: str, updated_record: SummaryRecord) -> Path`.

- [ ] **Step 1: Add failing happy-path and identity tests**

Append tests that save an original record, replace it with `model_copy(update={...})`, and assert the returned path and persisted record. Add a second test passing a different `updated_record.id` and assert `("save", "INVALID_RECORD", False)` while the original remains unchanged.

```python
def test_replace_atomically_overwrites_an_existing_valid_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    original = make_record("example")
    repository.save(original)
    updated = original.model_copy(update={"summary": "Updated summary."})

    path = repository.replace("example", updated)

    assert path == tmp_path / "example.json"
    assert repository.get("example") == updated
    assert not list(tmp_path.glob("*.tmp"))


def test_replace_rejects_a_record_id_mismatch_without_changing_data(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    original = make_record("example")
    repository.save(original)

    with pytest.raises(DigestError) as raised:
        repository.replace("example", make_record("other"))

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save", "INVALID_RECORD", False
    )
    assert repository.get("example") == original
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_storage.py::test_replace_atomically_overwrites_an_existing_valid_record tests/test_storage.py::test_replace_rejects_a_record_id_mismatch_without_changing_data -v`

Expected: FAIL because `SummaryRepository` has no `replace` method.

- [ ] **Step 3: Implement the minimal replacement boundary**

Add this public method before `set_status`:

```python
def replace(self, record_id: str, updated_record: SummaryRecord) -> Path:
    """Atomically replace one existing record after identity and URL checks."""
    self.get(record_id)
    if updated_record.id != record_id:
        raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False)
    for existing in self._load_all():
        if existing.id != record_id and str(existing.canonical_url) == str(updated_record.canonical_url):
            raise DigestError("save", "DUPLICATE_URL", "A summary already exists for this URL", False)
    destination = self._record_path(record_id)
    self._write(destination, updated_record)
    return destination
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_storage.py -v`

Expected: all storage tests PASS.

- [ ] **Step 5: Add failing conflict and write-failure preservation tests**

Add tests that: (a) save `first` and `second`, try replacing `second` with `first`'s canonical URL, and assert `save / DUPLICATE_URL`; (b) monkeypatch `storage.os.replace` to raise `OSError`, assert `save / WRITE_FAILED / True`, assert the original JSON still loads, and assert no `*.tmp` remains.

- [ ] **Step 6: Run the new tests and verify their expected state**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_storage.py -v`

Expected: conflict test PASS from Step 3; write-failure preservation test PASS through existing `_write()` semantics. If either fails, change only `replace()`/`_write()` enough to satisfy the repository contract and rerun until GREEN.

- [ ] **Step 7: Commit Task 1**

```powershell
git add -- src/ai_digest/storage.py tests/test_storage.py
git commit -m "feat: atomically replace summary records"
```

### Task 2: Editor Runner and Manual Edit Workflow

**Files:**
- Create: `src/ai_digest/editing.py`
- Create: `tests/test_editing.py`

**Interfaces:**
- Consumes: `SummaryRepository.get()`, `SummaryRepository.replace()`, `SummaryRecord`, `DigestError`.
- Produces: `EditorRunner(environment: Mapping[str, str], platform: str, command_runner: Callable[..., CompletedProcess])`, `EditorRunner.edit(path: Path) -> None`, and `EditSummaryWorkflow(repository, editor, clock).run(record_id: str) -> SummaryRecord`.

- [ ] **Step 1: Write failing editor selection and subprocess tests**

Create `tests/test_editing.py` with a fake command runner that captures `args`, `check`, and `shell`. Verify `VISUAL="code --wait"` wins over `EDITOR`, the temporary path is the last argument, and invocation uses `check=False`, `shell=False`. Add Windows fallback `notepad.exe`, non-Windows missing configuration (`input / EDITOR_NOT_CONFIGURED`), nonzero return code, and `OSError` (`input / EDITOR_FAILED`) cases.

```python
def test_editor_runner_prefers_visual_and_never_uses_a_shell(tmp_path) -> None:
    calls: list[dict[str, object]] = []
    def run(args, *, check, shell):
        calls.append({"args": args, "check": check, "shell": shell})
        return subprocess.CompletedProcess(args, 0)
    editor = EditorRunner(
        {"VISUAL": "code --wait", "EDITOR": "ignored"},
        platform="win32",
        command_runner=run,
    )

    editor.edit(tmp_path / "record.json")

    assert calls == [{
        "args": ["code", "--wait", str(tmp_path / "record.json")],
        "check": False,
        "shell": False,
    }]
```

- [ ] **Step 2: Run editor tests and verify RED**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_editing.py -v`

Expected: collection FAIL because `ai_digest.editing` does not exist.

- [ ] **Step 3: Implement `EditorRunner` minimally**

Create `src/ai_digest/editing.py` with this editor boundary (imports include `Mapping` from `collections.abc`, `Path`, `shlex`, `subprocess`, and the domain error):

```python
class EditorRunner:
    def __init__(
        self,
        environment: Mapping[str, str],
        *,
        platform: str,
        command_runner: Callable[..., subprocess.CompletedProcess[object]],
    ) -> None:
        self._environment = environment
        self._platform = platform
        self._command_runner = command_runner

    def edit(self, path: Path) -> None:
        configured = next(
            (
                value.strip()
                for name in ("VISUAL", "EDITOR")
                if (value := self._environment.get(name, "")).strip()
            ),
            None,
        )
        try:
            if configured is not None:
                command = shlex.split(configured)
                if not command:
                    raise ValueError("empty editor command")
            elif self._platform == "win32":
                command = ["notepad.exe"]
            else:
                raise DigestError(
                    "input",
                    "EDITOR_NOT_CONFIGURED",
                    "VISUAL or EDITOR must identify a text editor",
                    False,
                )
            result = self._command_runner(
                [*command, str(path)], check=False, shell=False
            )
        except DigestError:
            raise
        except (OSError, ValueError) as error:
            raise DigestError(
                "input", "EDITOR_FAILED", "The text editor could not be run", False
            ) from error
        if result.returncode != 0:
            raise DigestError(
                "input", "EDITOR_FAILED", "The text editor could not be run", False
            )
```

- [ ] **Step 4: Run editor tests and verify GREEN**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_editing.py -v`

Expected: all editor selection/execution tests PASS.

- [ ] **Step 5: Write failing edit-workflow tests**

In the same file, use a real `SummaryRepository(tmp_path / "summaries")` and a fake editor whose `edit(path)` rewrites the JSON. Cover:

```python
@pytest.mark.parametrize(
    ("alias", "value"),
    [
        ("title", "Edited title"),
        ("author", "Edited author"),
        ("sourcePublishedAt", "2026-08-10T10:00:00+08:00"),
        ("summary", "Edited summary."),
        ("keyPoints", ["A", "B", "C"]),
        ("category", CATEGORY),
        ("tags", ["Edited"]),
        ("editorial", "Edited editorial."),
        ("status", "archived"),
    ],
)
def test_edit_workflow_allows_each_content_field(alias, value, tmp_path): ...
```

Also cover every protected alias (`schemaVersion`, `id`, `canonicalUrl`, `sourceType`, `createdAt`), malformed JSON, invalid UTF-8 bytes, Schema failure, caller-supplied `updatedAt` being replaced with `NOW`, no-content-change success, repository write failure, and temporary-file cleanup in every path. Assert all failures leave the original record unchanged.

- [ ] **Step 6: Run workflow tests and verify RED**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_editing.py -v`

Expected: FAIL because `EditSummaryWorkflow` does not exist.

- [ ] **Step 7: Implement `EditSummaryWorkflow`**

Add:

```python
_PROTECTED_ALIASES = ("schemaVersion", "id", "canonicalUrl", "sourceType", "createdAt")

class EditSummaryWorkflow:
    def __init__(self, repository: SummaryRepository, editor: EditorRunner, clock: Callable[[], datetime]) -> None: ...
    def run(self, record_id: str) -> SummaryRecord:
        original = self._repository.get(record_id)
        original_payload = original.model_dump(mode="json", by_alias=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", delete=False
            ) as handle:
                json.dump(original_payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                temporary_path = Path(handle.name)
            self._editor.edit(temporary_path)
            edited_payload = json.loads(temporary_path.read_text(encoding="utf-8"))
            for alias in _PROTECTED_ALIASES:
                if edited_payload.get(alias) != original_payload[alias]:
                    raise DigestError("save", "PROTECTED_FIELD_CHANGED", "Protected summary fields cannot be changed", False)
            edited_payload["updatedAt"] = self._clock().isoformat()
            updated = SummaryRecord.model_validate(edited_payload)
            self._repository.replace(record_id, updated)
            return updated
        except DigestError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
```

Keep public error messages constant and do not include the temporary path or parser exception.

- [ ] **Step 8: Run editing and storage tests**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_editing.py tests/test_storage.py -v`

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```powershell
git add -- src/ai_digest/editing.py tests/test_editing.py
git commit -m "feat: edit local summary records safely"
```

### Task 3: Source-Based Regeneration Workflow

**Files:**
- Create: `src/ai_digest/regeneration.py`
- Create: `tests/test_regeneration.py`

**Interfaces:**
- Consumes: `Extractor.extract(url)`, `Summarizer.summarize(article)`, `Classifier.predict(text)`, `SummaryRepository.get/list/replace`.
- Produces: `RegenerateSummaryWorkflow(..., on_progress=None).run(record_id: str, now: datetime) -> SummaryRecord`.

- [ ] **Step 1: Write the failing orchestration test**

Build focused fakes like `tests/test_workflow.py`. Save an archived existing record, return a changed `ExtractedArticle` and `SummaryDraft`, and assert event order, progress order, classifier input, and all field invariants.

```python
assert progress == ["input", "extract", "summarize", "classify", "validate", "save"]
assert result.id == original.id
assert result.created_at == original.created_at
assert result.status == original.status
assert result.updated_at == NOW
assert result.title == article.title
assert result.summary == draft.summary
assert repository.get(original.id) == result
```

- [ ] **Step 2: Run the test and verify RED**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_regeneration.py -v`

Expected: collection FAIL because `ai_digest.regeneration` does not exist.

- [ ] **Step 3: Implement the minimum regeneration workflow**

Create a class mirroring the dependency style of `AddArticleWorkflow` with this complete field mapping and stage order:

```python
class RegenerateSummaryWorkflow:
    def __init__(
        self,
        extractor: Extractor,
        summarizer: Summarizer,
        classifier: Classifier,
        repository: SummaryRepository,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._extractor = extractor
        self._summarizer = summarizer
        self._classifier = classifier
        self._repository = repository
        self._on_progress = on_progress or (lambda stage: None)

    def run(self, record_id: str, now: datetime) -> SummaryRecord:
        self._on_progress("input")
        original = self._repository.get(record_id)

        self._on_progress("extract")
        article = self._extractor.extract(str(original.canonical_url))
        resolved_url = str(article.canonical_url)
        if any(
            existing.id != record_id
            and str(existing.canonical_url) == resolved_url
            for existing in self._repository.list()
        ):
            raise DigestError(
                "input", "DUPLICATE_URL", "A summary already exists for this URL", False
            )

        self._on_progress("summarize")
        draft = self._summarizer.summarize(article)
        classifier_text = "\n\n".join(
            [article.title, draft.summary, "\n".join(draft.key_points)]
        )
        self._on_progress("classify")
        category = self._classifier.predict(classifier_text)
        if category not in VALID_CATEGORIES:
            raise DigestError(
                "classify", "INVALID_CATEGORY", "Category is not configured", False
            )

        self._on_progress("validate")
        try:
            updated = SummaryRecord(
                schemaVersion=1,
                id=original.id,
                canonicalUrl=article.canonical_url,
                sourceType=article.source_type,
                title=article.title,
                author=article.author,
                sourcePublishedAt=article.published_at,
                createdAt=original.created_at,
                updatedAt=now,
                summary=draft.summary,
                keyPoints=draft.key_points,
                category=category,
                tags=draft.tags,
                editorial=draft.editorial,
                status=original.status,
            )
        except ValidationError as error:
            raise DigestError(
                "save", "INVALID_RECORD", "Summary record is invalid", False
            ) from error

        self._on_progress("save")
        self._repository.replace(record_id, updated)
        return updated
```

- [ ] **Step 4: Run the orchestration test and verify GREEN**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_regeneration.py -v`

Expected: PASS.

- [ ] **Step 5: Add failing boundary tests**

Cover missing target, extractor failure, resolved canonical collision, summarizer failure, invalid classifier category, classifier failure, Pydantic validation failure, and repository failure. For the collision case assert the event list contains extraction and repository preflight but no `summarize`; for every failure assert the original repository record is unchanged.

- [ ] **Step 6: Run boundary tests and complete minimal error mapping**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_regeneration.py -v`

Expected: tests initially identify any missing boundary behavior; add only the same `INVALID_CATEGORY`, `INVALID_RECORD`, and `DUPLICATE_URL` mappings already used by `AddArticleWorkflow`, then rerun to PASS.

- [ ] **Step 7: Run both workflow suites**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_workflow.py tests/test_regeneration.py -v`

Expected: PASS, proving creation behavior remains unchanged.

- [ ] **Step 8: Commit Task 3**

```powershell
git add -- src/ai_digest/regeneration.py tests/test_regeneration.py
git commit -m "feat: regenerate existing summaries from source"
```

### Task 4: CLI Commands and Production Dependency Composition

**Files:**
- Modify: `src/ai_digest/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `EditorRunner`, `EditSummaryWorkflow`, `RegenerateSummaryWorkflow`.
- Produces: `ai-digest edit RECORD_ID` and `ai-digest regenerate RECORD_ID`.

- [ ] **Step 1: Write failing injected CLI command tests**

Extend `create_app()` with optional factories while preserving existing callers:

```python
edit_workflow_factory: Callable[[], EditSummaryWorkflow] | None = None,
regenerate_workflow_factory: Callable[[Callable[[str], None]], RegenerateSummaryWorkflow] | None = None,
```

Use fake workflows to verify `edit` calls `run(record_id)`, `regenerate` calls `run(record_id, NOW)`, progress events are emitted for regeneration, successful output has `stage`, `id`, and repository-derived path, and `DigestError` is emitted to stderr with exit code 1.

- [ ] **Step 2: Run focused CLI tests and verify RED**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_cli.py -k "edit or regenerate" -v`

Expected: FAIL because commands/factory parameters do not exist.

- [ ] **Step 3: Add the two Typer commands with injected defaults**

Inside `create_app`, resolve optional factories to defaults backed by the injected repository and clock. Add commands that call their workflows, then emit:

```python
path = repository_factory().root / f"{record.id}.json"
_emit({"stage": "complete", "id": record.id, "path": str(path)})
```

Catch only `DigestError` through the existing `report_error()` boundary.

- [ ] **Step 4: Run focused CLI tests and verify GREEN**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_cli.py -k "edit or regenerate" -v`

Expected: PASS.

- [ ] **Step 5: Write failing production-composition tests**

Add tests proving:

- production `edit` with both provider keys removed does not call `_provider`, `_summarizer`, `_classifier`, extractor construction, or external clients;
- production `regenerate` defaults to Gemini and constructs the same router/summarizer/classifier boundaries as `add`;
- selecting OpenAI constructs only OpenAI summarizer/transcriber dependencies;
- missing selected provider key returns existing `MISSING_API_KEY` before the regeneration workflow runs;
- `_editor_runner()` injects `os.environ`, `sys.platform`, and `subprocess.run` into `EditorRunner`.

- [ ] **Step 6: Implement production factories**

Add `_editor_runner()`, `_edit_workflow()`, and `_regenerate_workflow(on_progress=None)`. Reuse a small private `_source_dependencies(provider)` helper only if tests expose harmful duplication; otherwise keep the existing `_workflow()` unchanged and construct the same router dependencies explicitly for regeneration.

- [ ] **Step 7: Run the full CLI suite**

Run: `D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`

Expected: PASS with existing add/list/show/archive/publish/evaluate behavior unchanged.

- [ ] **Step 8: Commit Task 4**

```powershell
git add -- src/ai_digest/cli.py tests/test_cli.py
git commit -m "feat: expose edit and regenerate CLI commands"
```

### Task 5: Documentation, Progress, and Complete Verification

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: verified CLI behavior from Tasks 1–4.
- Produces: accurate user operation guide and current project record.

- [ ] **Step 1: Update README with exact operations**

Document:

```powershell
$env:VISUAL = "code --wait"
ai-digest edit <record-id>
ai-digest regenerate <record-id>
```

State the `VISUAL` → `EDITOR` → Windows Notepad selection order, protected fields, Schema validation, atomic preservation on failure, provider/key selection, and that regeneration makes one paid summary call after successful extraction/preflight.

- [ ] **Step 2: Run focused and complete Python tests**

Run:

```powershell
D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest tests/test_storage.py tests/test_editing.py tests/test_regeneration.py tests/test_cli.py -v
D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest
```

Expected: all focused tests PASS; complete suite has no failures. Existing Windows symlink skips and the existing third-party `google-genai` deprecation warning may remain and must be reported exactly.

- [ ] **Step 3: Validate stored data and deployment safety**

Run:

```powershell
D:\Project\AI-Summary\.venv\Scripts\python.exe -c "from pathlib import Path; from ai_digest.storage import SummaryRepository; records=SummaryRepository(Path('data/summaries')).list(); print(f'validated={len(records)}')"
D:\Project\AI-Summary\.venv\Scripts\python.exe scripts/verify_deployment.py --tracked
git diff --check
```

Expected: all repository records validate; verifier and diff check exit 0.

- [ ] **Step 4: Run a key-free local edit smoke with an injected editor command**

Use a temporary `AI_DIGEST_SUMMARY_ROOT` copied from one fixture and an `EDITOR` command supplied by a test helper executable; do not modify production `data/summaries`. Confirm command exit 0, editable content changed, protected fields stayed fixed, `updatedAt` advanced, and no temporary JSON remains.

- [ ] **Step 5: Update project progress only from observed evidence**

Add a dated `progress.md` entry with actual focused/full test counts, stored-data count, verifier results, limitations, commit hashes, and the next step. Check the local-edit/regenerate item in `todo.md` only after Steps 2–4 pass. Do not claim a paid live regeneration or remote Pages deployment unless separately authorized and actually executed.

- [ ] **Step 6: Review documentation consistency and diff scope**

Run:

```powershell
rg -n "edit|regenerate|本機編輯|重新產生|最後更新|下次續作" README.md progress.md todo.md docs/superpowers/specs/2026-08-30-local-edit-regenerate-design.md
git diff --check
git status --short --branch
```

Expected: commands and limitations agree across documents; only intended feature files are modified.

- [ ] **Step 7: Commit Task 5**

```powershell
git add -- README.md progress.md todo.md
git commit -m "docs: record local edit and regeneration support"
```

- [ ] **Step 8: Final branch verification before completion or integration**

Run:

```powershell
D:\Project\AI-Summary\.venv\Scripts\python.exe -m pytest
D:\Project\AI-Summary\.venv\Scripts\python.exe scripts/verify_deployment.py --tracked
git diff --check master...HEAD
git status --short --branch
```

Expected: no test failures; verifier and diff check exit 0; feature worktree clean. Request code review before presenting merge/push options.
