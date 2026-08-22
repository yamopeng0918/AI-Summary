# Provider-aligned Audio Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `AI_DIGEST_PROVIDER` select both the summarizer and the no-caption YouTube audio transcriber, adding Gemini Files API transcription while preserving OpenAI support and preventing cross-provider fallback.

**Architecture:** Keep `YouTubeExtractor` dependent only on the existing `AudioTranscriber` protocol. Add a focused `GeminiAudioTranscriber` adapter with upload/generate/delete lifecycle management, then centralize normalized provider selection in CLI composition so one provider and one API key govern the complete `add` workflow.

**Tech Stack:** Python 3.12+, Pydantic 2, Typer, `google-genai`, OpenAI Python SDK, `httpx`, pytest, yt-dlp, FFmpeg, Astro, Vitest.

## Global Constraints

- Follow strict TDD: write one minimal failing test, verify the expected failure, add the minimum implementation, rerun focused tests, then refactor only while green.
- `AI_DIGEST_PROVIDER=gemini` uses only `GEMINI_API_KEY`; `AI_DIGEST_PROVIDER=openai` uses only `OPENAI_API_KEY`.
- Do not add automatic fallback or a separate transcription-provider setting.
- Preserve captions-first extraction. Do not construct a transcriber or download audio when a usable caption exists.
- Do not expose API keys, complete source URLs, transcripts, local paths, Gemini file names/URIs, prompts, or raw SDK responses in public errors.
- Delete every successfully uploaded Gemini file after success, failure, or interruption. Preserve the primary safe failure if generation and cleanup both fail.
- Keep local media cleanup, the 600-second default chunk duration, the 24 MiB chunk limit, and the 7200-second video limit.
- Replace `AI_DIGEST_TRANSCRIPTION_MODEL` with `GEMINI_TRANSCRIPTION_MODEL` and `OPENAI_TRANSCRIPTION_MODEL`.
- Daily tests must use fakes and local fixtures only; no external network, binaries, or paid API calls.
- Preserve unrelated user changes. Do not push, create a PR, or deploy.

---

## File Structure

- Create `src/ai_digest/transcribers/gemini.py`: Gemini Files API transcription adapter, safe error mapping, and remote file cleanup.
- Create `tests/test_gemini_transcriber.py`: focused lifecycle, ordering, validation, cleanup, interruption, and leak-safety tests.
- Modify `src/ai_digest/cli.py`: normalized provider selection and provider-aligned summarizer/transcriber factories.
- Modify `tests/test_cli.py`: provider/key/model routing and lazy no-caption behavior.
- Modify `.env.example`: provider-specific transcription model variables.
- Modify `README.md`: provider-aligned configuration and Gemini audio behavior.
- Modify `docs/superpowers/specs/2026-08-21-youtube-source-design.md`: supersession note only; do not rewrite historical details.
- Modify `progress.md`: verified results, risks, external versions, decisions, and next step.
- Modify `todo.md`: mark real YouTube acceptance complete only after both approved live cases pass.

---

### Task 1: Gemini Transcriber Successful Lifecycle

**Files:**
- Create: `tests/test_gemini_transcriber.py`
- Create: `src/ai_digest/transcribers/gemini.py`

**Interfaces:**
- Consumes: `AudioTranscriber.transcribe(chunks: list[Path]) -> str` from `src/ai_digest/transcribers/__init__.py`.
- Produces: `GeminiAudioTranscriber(client: Any, model: str)` and `lazy_gemini_transcriber(api_key: str | None, model: str) -> GeminiAudioTranscriber`.
- Gemini client contract: `files.upload(file=Path) -> File`, `models.generate_content(model=str, contents=[str, File]) -> response`, and `files.delete(name=str)`.

- [ ] **Step 1: Write the failing missing-key and ordered-lifecycle tests**

Create `tests/test_gemini_transcriber.py` with these fakes and assertions:

```python
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_digest.domain import DigestError
from ai_digest.transcribers import gemini as gemini_transcriber
from ai_digest.transcribers.gemini import GeminiAudioTranscriber, lazy_gemini_transcriber


class FakeFiles:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events
        self.uploaded = 0

    def upload(self, *, file: Path) -> object:
        self.uploaded += 1
        self.events.append(("upload", file.name))
        return SimpleNamespace(name=f"files/chunk-{self.uploaded}")

    def delete(self, *, name: str) -> None:
        self.events.append(("delete", name))


class FakeModels:
    def __init__(self, events: list[tuple[str, str]], responses: list[object]) -> None:
        self.events = events
        self.responses = iter(responses)

    def generate_content(self, *, model: str, contents: list[object]) -> object:
        uploaded = contents[1]
        self.events.append(("generate", f"{model}:{uploaded.name}"))
        assert contents[0] == GeminiAudioTranscriber.TRANSCRIPTION_PROMPT
        return next(self.responses)


def make_chunk(root: Path, name: str) -> Path:
    chunk = root / name
    chunk.write_bytes(b"audio")
    return chunk


def test_missing_key_fails_before_constructing_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gemini_transcriber.genai,
        "Client",
        lambda **kwargs: pytest.fail("Gemini client must not be constructed"),
    )

    with pytest.raises(DigestError) as raised:
        lazy_gemini_transcriber(None, "gemini-3.6-flash")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "MISSING_API_KEY",
        "message": "GEMINI_API_KEY is required for YouTube audio transcription",
        "retryable": False,
    }


def test_transcribes_chunks_in_order_and_deletes_each_remote_file(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=FakeFiles(events),
        models=FakeModels(
            events,
            [SimpleNamespace(text="第一段逐字稿"), SimpleNamespace(text="第二段逐字稿")],
        ),
    )
    chunks = [make_chunk(tmp_path, "chunk-0000.mp3"), make_chunk(tmp_path, "chunk-0001.mp3")]

    result = GeminiAudioTranscriber(client, "gemini-3.6-flash").transcribe(chunks)

    assert result == "第一段逐字稿\n第二段逐字稿"
    assert events == [
        ("upload", "chunk-0000.mp3"),
        ("generate", "gemini-3.6-flash:files/chunk-1"),
        ("delete", "files/chunk-1"),
        ("upload", "chunk-0001.mp3"),
        ("generate", "gemini-3.6-flash:files/chunk-2"),
        ("delete", "files/chunk-2"),
    ]
```

- [ ] **Step 2: Run the new tests and verify red**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ai_digest.transcribers.gemini'`.

- [ ] **Step 3: Implement the minimum successful adapter**

Create `src/ai_digest/transcribers/gemini.py`:

```python
"""Safe Gemini adapter for audio transcription."""

from pathlib import Path
from typing import Any

from google import genai

from ai_digest.domain import DigestError


class GeminiAudioTranscriber:
    """Transcribe local audio chunks with Gemini and remove uploaded files."""

    TRANSCRIPTION_PROMPT = (
        "請忠實轉錄這段音訊。只輸出依原語言呈現的完整逐字稿；"
        "不要摘要、翻譯、補寫、評論或加入格式說明。"
    )

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def transcribe(self, chunks: list[Path]) -> str:
        completed: list[str] = []
        for chunk in chunks:
            uploaded = self._client.files.upload(file=chunk)
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=[self.TRANSCRIPTION_PROMPT, uploaded],
                )
                text = response.text.strip()
            finally:
                self._client.files.delete(name=uploaded.name)
            completed.append(text)
        return "\n".join(completed)


def lazy_gemini_transcriber(api_key: str | None, model: str) -> GeminiAudioTranscriber:
    """Build the Gemini client only when audio fallback needs it."""
    if not api_key:
        raise DigestError(
            "input",
            "MISSING_API_KEY",
            "GEMINI_API_KEY is required for YouTube audio transcription",
            False,
        )
    return GeminiAudioTranscriber(genai.Client(api_key=api_key), model)
```

- [ ] **Step 4: Run the focused tests and verify green**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Confirm the adapter satisfies the protocol structurally**

Append this test:

```python
from ai_digest.transcribers import AudioTranscriber


def accepts_transcriber(value: AudioTranscriber) -> AudioTranscriber:
    return value


def test_gemini_transcriber_satisfies_audio_transcriber_contract() -> None:
    client = SimpleNamespace(files=object(), models=object())
    assert accepts_transcriber(GeminiAudioTranscriber(client, "model")) is not None
```

Run the focused file again and expect 3 passing tests.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- src/ai_digest/transcribers/gemini.py tests/test_gemini_transcriber.py
git diff --cached --check
git commit -m "feat: transcribe audio with Gemini"
```

---

### Task 2: Gemini Failure Mapping and Remote Cleanup

**Files:**
- Modify: `tests/test_gemini_transcriber.py`
- Modify: `src/ai_digest/transcribers/gemini.py`

**Interfaces:**
- Consumes: `GeminiAudioTranscriber` from Task 1 and `google.genai.errors` exception types already used by `GeminiSummarizer`.
- Produces: safe `TRANSCRIPTION_TIMEOUT`, `TRANSCRIPTION_RATE_LIMITED`, and `TRANSCRIPTION_FAILED` mappings with deterministic cleanup.

- [ ] **Step 1: Add failing response-validation and no-partial-result tests**

Add tests parameterized over `None`, `123`, `""`, and whitespace-only `response.text`; each must assert:

```python
assert raised.value.as_dict() == {
    "stage": "extract",
    "code": "TRANSCRIPTION_FAILED",
    "message": "Audio transcription response is invalid",
    "retryable": False,
}
assert raised.value.__cause__ is None
```

Add a two-chunk test where the second response is blank. Assert both uploaded files are deleted and no transcript is returned.

- [ ] **Step 2: Run only the new validation tests and verify red**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py -k "invalid or partial" -v
```

Expected: FAIL because Task 1 calls `.strip()` on malformed values or accepts blank text.

- [ ] **Step 3: Add a safe response reader**

Implement and use this method:

```python
    @staticmethod
    def _response_text(response: object) -> str:
        try:
            raw = getattr(response, "text", None)
        except Exception:
            raw = None
        if not isinstance(raw, str) or not raw.strip():
            raise DigestError(
                "extract",
                "TRANSCRIPTION_FAILED",
                "Audio transcription response is invalid",
                False,
            ) from None
        return raw.strip()
```

Run the validation tests and expect them to pass.

- [ ] **Step 4: Add failing SDK and transport error mapping tests**

Use fake upload/generate/delete methods that raise one supplied exception. Cover:

```python
[
    (httpx.TimeoutException("SECRET"), "TRANSCRIPTION_TIMEOUT", True),
    (httpx.TransportError("SECRET"), "TRANSCRIPTION_FAILED", True),
    (errors.ClientError(429, {"message": "SECRET"}, None), "TRANSCRIPTION_RATE_LIMITED", True),
    (errors.ClientError(400, {"message": "SECRET"}, None), "TRANSCRIPTION_FAILED", False),
    (errors.ServerError(503, {"message": "SECRET"}, None), "TRANSCRIPTION_FAILED", True),
    (errors.UnknownApiResponseError(200, {"message": "SECRET"}, None), "TRANSCRIPTION_FAILED", False),
    (OSError("SECRET C:\\private\\chunk.mp3"), "TRANSCRIPTION_FAILED", False),
    (RuntimeError("SECRET files/private"), "TRANSCRIPTION_FAILED", False),
]
```

For every case, assert the public message is one of the fixed safe messages and that `"SECRET"`, `"private"`, and `"chunk.mp3"` do not occur in `str(raised.value)` or the rendered exception chain.

- [ ] **Step 5: Run the mapping tests and verify red**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py -k "maps or leak" -v
```

Expected: FAIL with raw fake exceptions because Task 1 has no mapping boundary.

- [ ] **Step 6: Implement one safe operation boundary**

Add imports for `httpx` and `google.genai.errors`, then add:

```python
def _safe_failure(error: Exception) -> DigestError:
    if isinstance(error, httpx.TimeoutException):
        return DigestError("extract", "TRANSCRIPTION_TIMEOUT", "Audio transcription timed out", True)
    if isinstance(error, errors.ClientError) and error.code == 429:
        return DigestError(
            "extract", "TRANSCRIPTION_RATE_LIMITED", "Audio transcription is rate limited", True
        )
    if isinstance(error, (httpx.TransportError, errors.ServerError)):
        return DigestError(
            "extract", "TRANSCRIPTION_FAILED", "Audio transcription request failed", True
        )
    return DigestError(
        "extract", "TRANSCRIPTION_FAILED", "Audio transcription request failed", False
    )
```

Refactor each chunk through a `_transcribe_chunk(chunk: Path) -> str` helper. Catch `Exception`, convert with `_safe_failure`, and raise the safe error `from None`. Do not catch `KeyboardInterrupt` or `SystemExit`.

- [ ] **Step 7: Add failing cleanup precedence and interruption tests**

Add these scenarios:

- upload fails: delete is never called;
- generation fails: delete is called exactly once;
- deletion fails after successful generation: safe non-retryable `TRANSCRIPTION_FAILED`;
- generation and deletion both fail: generation's safe code/retryability wins;
- `KeyboardInterrupt` or `SystemExit` during generation: delete runs, then the original process-control exception propagates;
- `KeyboardInterrupt` or `SystemExit` during deletion: the original process-control exception propagates.

- [ ] **Step 8: Implement deterministic cleanup precedence**

Use this control shape inside `_transcribe_chunk`:

```python
        uploaded: object | None = None
        primary: BaseException | None = None
        text: str | None = None
        try:
            uploaded = self._client.files.upload(file=chunk)
            response = self._client.models.generate_content(
                model=self._model,
                contents=[self.TRANSCRIPTION_PROMPT, uploaded],
            )
            text = self._response_text(response)
        except BaseException as error:
            primary = error
        finally:
            cleanup: BaseException | None = None
            if uploaded is not None:
                try:
                    self._client.files.delete(name=uploaded.name)
                except BaseException as error:
                    cleanup = error

        if isinstance(primary, (KeyboardInterrupt, SystemExit)):
            raise primary
        if primary is not None:
            if isinstance(primary, DigestError):
                raise primary
            if isinstance(primary, Exception):
                raise _safe_failure(primary) from None
        if isinstance(cleanup, (KeyboardInterrupt, SystemExit)):
            raise cleanup
        if cleanup is not None:
            raise DigestError(
                "extract",
                "TRANSCRIPTION_FAILED",
                "Audio transcription cleanup failed",
                False,
            ) from None
        assert text is not None
        return text
```

Keep this helper private and append to `completed` only after it returns.

- [ ] **Step 9: Run all Gemini and existing OpenAI transcriber tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_gemini_transcriber.py tests/test_openai_transcriber.py -v
```

Expected: all tests pass; neither suite uses network or real credentials.

- [ ] **Step 10: Commit Task 2**

```powershell
git add -- src/ai_digest/transcribers/gemini.py tests/test_gemini_transcriber.py
git diff --cached --check
git commit -m "fix: secure Gemini transcription lifecycle"
```

---

### Task 3: Align CLI Provider, Key, and Model Selection

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_digest/cli.py`

**Interfaces:**
- Consumes: `lazy_gemini_transcriber(api_key, model)` from Task 1 and existing `lazy_openai_transcriber(api_key, model)`.
- Produces: `_provider() -> Literal["gemini", "openai"]`, `_transcriber_factory(provider: str) -> Callable[[], AudioTranscriber]`, and provider-specific model selection.

- [ ] **Step 1: Replace the existing YouTube wiring test with two failing provider cases**

Parameterize `test_production_wires_youtube_transcriber_for_selected_provider` with:

```python
[
    ("gemini", "GEMINI_API_KEY", "GEMINI_TRANSCRIPTION_MODEL", "gemini-3.6-flash"),
    ("openai", "OPENAI_API_KEY", "OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe"),
]
```

Monkeypatch both lazy factory functions. Assert only the selected factory is called, it receives the selected key and expected default model, and constructing `_youtube_extractor()` does not call either lazy factory until `transcriber_factory()` is invoked.

- [ ] **Step 2: Run the focused CLI wiring tests and verify red**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py -k "youtube_transcriber_for_selected_provider" -v
```

Expected: Gemini case fails because `_youtube_extractor()` always wires `lazy_openai_transcriber` and `AI_DIGEST_TRANSCRIPTION_MODEL`.

- [ ] **Step 3: Centralize provider parsing and selected transcriber composition**

In `src/ai_digest/cli.py`, import `Literal`, `AudioTranscriber`, and `lazy_gemini_transcriber`. Add:

```python
def _provider() -> Literal["gemini", "openai"]:
    provider = os.environ.get("AI_DIGEST_PROVIDER", "gemini").strip().lower()
    if provider not in {"gemini", "openai"}:
        raise DigestError(
            "input", "INVALID_PROVIDER", "AI_DIGEST_PROVIDER must be gemini or openai", False
        )
    return provider


def _transcriber_factory(provider: Literal["gemini", "openai"]) -> Callable[[], AudioTranscriber]:
    if provider == "gemini":
        return lambda: lazy_gemini_transcriber(
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GEMINI_TRANSCRIPTION_MODEL", "gemini-3.6-flash"),
        )
    return lambda: lazy_openai_transcriber(
        os.environ.get("OPENAI_API_KEY"),
        os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe"),
    )
```

Change `_summarizer` to accept a provider argument, `_youtube_extractor` to accept the same provider, and `_workflow` to resolve `_provider()` once before composing both branches:

```python
def _workflow(on_progress: Callable[[str], None] | None = None) -> AddArticleWorkflow:
    provider = _provider()
    return AddArticleWorkflow(
        extractor=ExtractorRouter(
            WebExtractor(client_factory=_web_client_factory),
            LazyExtractor(lambda: _youtube_extractor(provider)),
        ),
        summarizer=_summarizer(provider),
        classifier=_classifier(),
        repository=_repository(),
        on_progress=on_progress,
    )
```

Pass `_transcriber_factory(provider)` to `YouTubeExtractor`. Remove all reads of `AI_DIGEST_TRANSCRIPTION_MODEL`.

- [ ] **Step 4: Run the provider wiring tests and verify green**

Run the focused command from Step 2. Expected: both provider cases pass.

- [ ] **Step 5: Add failing key-isolation and model-override tests**

Add CLI tests proving:

- Gemini summarization and no-caption transcription work with `GEMINI_API_KEY` set and `OPENAI_API_KEY` absent.
- OpenAI summarization and no-caption transcription work with `OPENAI_API_KEY` set and `GEMINI_API_KEY` absent.
- Missing selected-provider key raises `MISSING_API_KEY` before the fake media object records `download`.
- Setting `GEMINI_TRANSCRIPTION_MODEL=gemini-custom` affects only Gemini.
- Setting `OPENAI_TRANSCRIPTION_MODEL=openai-custom` affects only OpenAI.
- A stale `AI_DIGEST_TRANSCRIPTION_MODEL=wrong-provider-model` is ignored.
- An invalid `AI_DIGEST_PROVIDER` still returns the existing safe `INVALID_PROVIDER` payload.

- [ ] **Step 6: Run the new CLI tests and verify red, then make the minimum composition corrections**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py -k "provider or transcription_model or no_caption" -v
```

Expected before corrections: at least the Gemini no-caption and stale-variable tests fail. Change only provider composition until all selected tests pass.

- [ ] **Step 7: Run all CLI, YouTube, and transcriber tests**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_cli.py tests/test_youtube_extractor.py tests/test_youtube_media.py tests/test_gemini_transcriber.py tests/test_openai_transcriber.py -v
```

Expected: all pass without external tools, network, or credentials.

- [ ] **Step 8: Commit Task 3**

```powershell
git add -- src/ai_digest/cli.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: align AI provider across ingestion"
```

---

### Task 4: Documentation, Complete Verification, and Live Acceptance

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-21-youtube-source-design.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: provider-aligned behavior from Tasks 1–3.
- Produces: accurate operator configuration and evidence-backed milestone status.

- [ ] **Step 1: Update configuration documentation**

Replace the single transcription model in `.env.example` with:

```dotenv
GEMINI_TRANSCRIPTION_MODEL=gemini-3.6-flash
OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe
AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS=600
AI_DIGEST_TRANSCRIPTION_MAX_CHUNK_BYTES=25165824
AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS=7200
```

In `README.md`, state that `AI_DIGEST_PROVIDER` selects both summary and no-caption transcription, only the selected key is required, there is no fallback, Gemini uses Files API with remote cleanup, and OpenAI remains supported. Remove every statement that a Gemini workflow needs `OPENAI_API_KEY` for no-caption videos.

Add this note near the top of `docs/superpowers/specs/2026-08-21-youtube-source-design.md`:

```markdown
> Superseded in part on 2026-08-22: provider selection for audio transcription now follows `AI_DIGEST_PROVIDER`; see `2026-08-22-provider-aligned-audio-transcription-design.md`. All other YouTube source constraints remain in force.
```

- [ ] **Step 2: Run documentation consistency searches**

```powershell
rg -n "AI_DIGEST_TRANSCRIPTION_MODEL|OPENAI_API_KEY.*YouTube|OpenAI.*語音轉文字|OpenAI-only" .env.example README.md docs progress.md todo.md
```

Expected: no active instructions retain the removed setting or claim that Gemini transcription needs OpenAI. Historical text is allowed only when immediately marked as superseded.

- [ ] **Step 3: Run the complete Python suite with a workspace basetemp**

```powershell
$testRoot = Join-Path (Resolve-Path '.').Path '.pytest-provider-transcription'
if (Test-Path -LiteralPath $testRoot) { throw "Refusing to overwrite existing test directory" }
& '.\.venv\Scripts\python.exe' -m pytest --basetemp $testRoot
```

Expected: all tests pass. Remove only the exact test directory after confirming it resolves to `D:\Project\AI-Summary\.pytest-provider-transcription`.

- [ ] **Step 4: Run frontend and production build verification**

```powershell
Push-Location site
npm.cmd test
npm.cmd run build
Pop-Location
```

Expected: all Vitest tests pass; Astro check reports zero errors/warnings/hints; production build exits 0.

- [ ] **Step 5: Validate schemas, tracked data, diff formatting, and sensitive output**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_domain.py tests/test_storage.py -v
git diff --check
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
Get-ChildItem -LiteralPath site/dist -Recurse -File |
    Where-Object { $_.Extension -in '.mp3','.m4a','.webm','.vtt','.srt' }
```

Expected: schema/storage tests pass; diff check exits 0; deployment verifier exits 0; media scan prints nothing.

- [ ] **Step 6: Confirm live prerequisites without printing secrets**

Refresh the current process PATH from machine/user environment, then run:

```powershell
yt-dlp --version
ffmpeg -version | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)) { throw 'GEMINI_API_KEY is unset' }
```

Expected: yt-dlp and FFmpeg versions print; key check produces no output and does not throw.

- [ ] **Step 7: Run the approved no-caption Gemini acceptance in isolation**

Use an absent, explicit workspace directory and process-only environment:

```powershell
$acceptanceRoot = 'D:\Project\AI-Summary\.youtube-acceptance-gemini'
if (Test-Path -LiteralPath $acceptanceRoot) { throw 'Acceptance directory already exists' }
$env:AI_DIGEST_PROVIDER = 'gemini'
$env:AI_DIGEST_SUMMARY_ROOT = $acceptanceRoot
& '.\.venv\Scripts\ai-digest.exe' add 'https://www.youtube.com/watch?v=4gciWspBVHw'
```

Expected: progress reaches `complete` and exactly one JSON file is created. This command may incur Gemini API usage and must not print the key, transcript, file URI, or local media path.

- [ ] **Step 8: Validate the live record and cleanup**

Load the JSON with `SummaryRecord.model_validate_json` and assert:

- `source_type == "youtube"`;
- canonical URL is exactly `https://www.youtube.com/watch?v=4gciWspBVHw`;
- `status == "published"`;
- summary and editorial are non-empty;
- key points count is between 3 and 5;
- raw JSON contains no repository path and no `.mp3`, `.m4a`, `.webm`, `.vtt`, `.srt`, `files/`, or Gemini URI reference.

After validation, resolve and verify the exact acceptance root, then delete only that isolated directory. Confirm no media files remain under the repository.

- [ ] **Step 9: Update progress and todo with actual evidence**

In `progress.md`, record:

- date and provider-aligned architecture decision;
- actual Python/frontend/build counts;
- installed yt-dlp and FFmpeg versions;
- both user-approved URLs and actual live outcomes;
- Gemini model actually used;
- any warning, limitation, cost risk, or unverified item;
- next milestone: define the first public social-post platform.

In `todo.md`, check `有字幕與無可用字幕各以一個使用者核准的真實公開案例驗收` only if the Gemini no-caption acceptance and the previously completed captioned acceptance both have recorded valid evidence.

- [ ] **Step 10: Re-run verification after documentation changes**

Run the complete Python suite, frontend tests/build, `git diff --check`, and deployment verifier again. Expected: all commands pass with the same or higher test counts and no sensitive output.

- [ ] **Step 11: Review scope and commit Task 4**

```powershell
git status --short
git diff --name-only
git diff --check
git add -- .env.example README.md docs/superpowers/specs/2026-08-21-youtube-source-design.md progress.md todo.md
git diff --cached --name-only
git commit -m "docs: verify provider-aligned YouTube ingestion"
```

Expected staged paths: only the five documentation/configuration files listed above. Do not stage proposal documents, generated site output, acceptance data, or pre-existing untracked files.

---

## Final Review Gate

- Map every requirement in `docs/superpowers/specs/2026-08-22-provider-aligned-audio-transcription-design.md` to a completed task above.
- Confirm `rg -n "AI_DIGEST_TRANSCRIPTION_MODEL" src tests .env.example README.md` returns no active code/config references.
- Confirm Gemini and OpenAI each work with only their own key in automated tests.
- Confirm captions still bypass media and both transcriber factories.
- Confirm Gemini remote cleanup has success, failure, dual-failure, and interruption coverage.
- Confirm the approved no-caption live record was validated and removed from the isolated directory.
- Confirm the worktree contains only intentional changes and the pre-existing untracked files remain untouched.
