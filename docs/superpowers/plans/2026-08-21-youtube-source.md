# YouTube Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe public YouTube ingestion with captions-first extraction and an OpenAI transcription fallback for videos without usable captions.

**Architecture:** Normalize supported YouTube URL forms before duplicate preflight, then dispatch through a shared extractor protocol to either the existing web extractor or an independent YouTube extractor. The YouTube extractor probes metadata, selects and cleans captions, and only invokes an isolated `yt-dlp`/FFmpeg/OpenAI media pipeline when captions are unavailable.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, OpenAI Python SDK, `yt-dlp` and FFmpeg executables, pytest, Astro 7, Zod, Vitest.

## Global Constraints

- Only public, directly readable single YouTube videos are in scope; never pass cookies, credentials, proxy settings, or access-control bypass flags.
- Reject private, members-only, login/age-gated, unavailable, currently-live, upcoming, and over-limit videos.
- `AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS` defaults to `7200`.
- `AI_DIGEST_TRANSCRIPTION_MODEL` defaults to `gpt-transcribe`.
- `AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS` receives a documented safe default during Task 5.
- Check `OPENAI_API_KEY` lazily and only after determining that no usable caption exists; do not download audio when it is missing.
- Never expose a complete source URL, transcript, temporary path, API key, or raw tool/SDK error in public errors.
- Temporary media and caption files must be removed after success, failure, or interruption.
- Daily tests use fixtures and fakes only; they must not require network access, external binaries, or paid APIs.
- Follow strict TDD for every behavior change and preserve unrelated user files and worktree changes.

---

## File Structure

- Create `src/ai_digest/source_urls.py`: recognize supported YouTube hosts/forms, validate video IDs, and return source canonical URLs.
- Create `src/ai_digest/extractors/base.py`: shared `Extractor` protocol used by the workflow and router.
- Create `src/ai_digest/extractors/router.py`: dispatch canonical URLs to independent web or YouTube extractors.
- Modify `src/ai_digest/domain.py`: carry `source_type` on extracted content and accept `youtube` in records.
- Modify `src/ai_digest/workflow.py`: use source canonicalization and persist the extractor-provided source type.
- Create `src/ai_digest/extractors/youtube_captions.py`: select caption tracks and normalize VTT content.
- Create `src/ai_digest/extractors/youtube_media.py`: safe argv-only subprocess boundary, isolated temporary directories, download, conversion, and chunking.
- Create `src/ai_digest/transcribers/openai.py`: lazy OpenAI client creation and safe transcription error mapping.
- Create `src/ai_digest/extractors/youtube.py`: metadata validation and captions-first orchestration.
- Modify `src/ai_digest/cli.py`: compose router, YouTube dependencies, settings, and lazy transcription factory.
- Modify `schemas/summary-v1.json`, `site/src/lib/summaries.ts`, and `site/src/lib/summary-loader.ts`: accept `sourceType: youtube`.
- Modify `.env.example`, `README.md`, `progress.md`, and `todo.md`: document dependencies, settings, verified status, risks, and next step.
- Create corresponding focused tests under `tests/`; modify `tests/test_workflow.py`, `tests/test_domain.py`, `tests/test_cli.py`, and `site/src/lib/summaries.test.ts` only where their existing contracts change.

---

### Task 1: YouTube URL Recognition and Canonicalization

**Files:**
- Create: `src/ai_digest/source_urls.py`
- Create: `tests/test_source_urls.py`

**Interfaces:**
- Consumes: `normalize_public_url(raw_url: str) -> str` from `ai_digest.url_normalizer`.
- Produces: `canonicalize_source_url(raw_url: str) -> str` and `is_youtube_url(url: str) -> bool`.

- [ ] **Step 1: Write parameterized failing tests for supported forms**

```python
import pytest

from ai_digest.source_urls import canonicalize_source_url, is_youtube_url


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12&utm_source=test",
        "https://youtu.be/dQw4w9WgXcQ?t=12",
        "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
    ],
)
def test_canonicalizes_supported_youtube_video_forms(raw_url: str) -> None:
    assert is_youtube_url(raw_url) is True
    assert canonicalize_source_url(raw_url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_preserves_existing_web_normalization() -> None:
    assert canonicalize_source_url("HTTPS://EXAMPLE.COM/a?utm_source=x&b=2") == "https://example.com/a?b=2"
```

- [ ] **Step 2: Run the supported-form tests and verify red**

Run: `pytest tests/test_source_urls.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'ai_digest.source_urls'`.

- [ ] **Step 3: Write failing tests for invalid YouTube pages and IDs**

```python
from ai_digest.domain import DigestError


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://www.youtube.com/@OpenAI",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://youtu.be/not valid",
        "https://www.youtube.com/watch?v=short",
    ],
)
def test_rejects_youtube_urls_that_are_not_valid_single_videos(raw_url: str) -> None:
    with pytest.raises(DigestError) as raised:
        canonicalize_source_url(raw_url)

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "UNSUPPORTED_YOUTUBE_URL",
        "message": "URL must identify one supported YouTube video",
        "retryable": False,
    }
```

- [ ] **Step 4: Implement the minimum URL module**

```python
"""Recognize and canonicalize supported source URLs."""

import re
from urllib.parse import parse_qs, urlsplit

from ai_digest.domain import DigestError
from ai_digest.url_normalizer import normalize_public_url


_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def is_youtube_url(url: str) -> bool:
    try:
        return (urlsplit(normalize_public_url(url)).hostname or "") in _YOUTUBE_HOSTS
    except DigestError:
        return False


def _unsupported() -> DigestError:
    return DigestError(
        "input", "UNSUPPORTED_YOUTUBE_URL", "URL must identify one supported YouTube video", False
    )


def canonicalize_source_url(raw_url: str) -> str:
    normalized = normalize_public_url(raw_url)
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    if host not in _YOUTUBE_HOSTS:
        return normalized

    if host == "youtu.be":
        candidate = parsed.path.removeprefix("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith(("/shorts/", "/embed/")):
        candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    else:
        raise _unsupported()
    if not _VIDEO_ID.fullmatch(candidate):
        raise _unsupported()
    return f"https://www.youtube.com/watch?v={candidate}"
```

- [ ] **Step 5: Run focused URL tests and the existing normalizer tests**

Run: `pytest tests/test_source_urls.py tests/test_url_normalizer.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- src/ai_digest/source_urls.py tests/test_source_urls.py
git commit -m "feat: canonicalize YouTube source URLs"
```

---

### Task 2: Shared Extractor Contract, Routing, and Source Type

**Files:**
- Create: `src/ai_digest/extractors/base.py`
- Create: `src/ai_digest/extractors/router.py`
- Create: `tests/test_extractor_router.py`
- Modify: `src/ai_digest/domain.py`
- Modify: `src/ai_digest/workflow.py`
- Modify: `tests/test_domain.py`
- Modify: `tests/test_workflow.py`

**Interfaces:**
- Consumes: `is_youtube_url(url: str) -> bool` and `canonicalize_source_url(raw_url: str) -> str` from Task 1.
- Produces: `Extractor.extract(url: str) -> ExtractedArticle`; `ExtractorRouter(web: Extractor, youtube: Extractor)`; `ExtractedArticle.source_type: Literal["web", "youtube"]`.

- [ ] **Step 1: Write failing domain and router tests**

```python
# tests/test_domain.py
def test_summary_and_extracted_article_accept_youtube_source_type() -> None:
    article = ExtractedArticle(
        canonicalUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        sourceType="youtube",
        title="影片",
        text="足夠的逐字稿內容",
    )
    assert article.source_type == "youtube"
    assert valid_record(sourceType="youtube").source_type == "youtube"
```

```python
# tests/test_extractor_router.py
from ai_digest.extractors.router import ExtractorRouter


class RecordingExtractor:
    def __init__(self, article):
        self.article = article
        self.urls = []

    def extract(self, url: str):
        self.urls.append(url)
        return self.article


def test_routes_canonical_youtube_url_only_to_youtube_extractor() -> None:
    web = RecordingExtractor(None)
    youtube = RecordingExtractor("youtube-result")
    router = ExtractorRouter(web=web, youtube=youtube)

    assert router.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube-result"
    assert web.urls == []
    assert youtube.urls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
```

- [ ] **Step 2: Run new tests and verify red**

Run: `pytest tests/test_domain.py::test_summary_and_extracted_article_accept_youtube_source_type tests/test_extractor_router.py -v`

Expected: failures because `sourceType="youtube"` and router/base modules are not supported yet.

- [ ] **Step 3: Add the extractor protocol, router, and source field**

```python
# src/ai_digest/extractors/base.py
from typing import Protocol

from ai_digest.domain import ExtractedArticle


class Extractor(Protocol):
    def extract(self, url: str) -> ExtractedArticle: ...
```

```python
# src/ai_digest/extractors/router.py
from ai_digest.domain import ExtractedArticle
from ai_digest.extractors.base import Extractor
from ai_digest.source_urls import is_youtube_url


class ExtractorRouter:
    def __init__(self, web: Extractor, youtube: Extractor) -> None:
        self._web = web
        self._youtube = youtube

    def extract(self, url: str) -> ExtractedArticle:
        return (self._youtube if is_youtube_url(url) else self._web).extract(url)
```

Modify the Pydantic models exactly as follows:

```python
class ExtractedArticle(DomainModel):
    canonical_url: HttpUrl
    source_type: Literal["web", "youtube"] = "web"
    title: str
    author: str | None = None
    published_at: datetime | None = None
    text: str


class SummaryRecord(DomainModel):
    # existing fields unchanged
    source_type: Literal["web", "youtube"] = Field(alias="sourceType")
```

- [ ] **Step 4: Make workflow use the shared contract and extracted source type**

Replace the `WebExtractor` import/type with `Extractor`, replace URL normalization with `canonicalize_source_url`, and set the record field from the article:

```python
from ai_digest.extractors.base import Extractor
from ai_digest.source_urls import canonicalize_source_url

# __init__
extractor: Extractor,

# run
canonical_url = canonicalize_source_url(raw_url)

# SummaryRecord construction
sourceType=article.source_type,
```

Update `make_article()` in `tests/test_workflow.py` to accept `source_type: str = "web"`, then add:

```python
def test_workflow_persists_youtube_source_type_and_canonical_url() -> None:
    events: list[str] = []
    article = make_article(source_type="youtube").model_copy(
        update={"canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    workflow, repository, _ = make_workflow(events, article=article)

    result = workflow.run("https://youtu.be/dQw4w9WgXcQ?t=10", NOW)

    assert str(result.canonical_url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert result.source_type == "youtube"
    assert repository.saved == [result]
```

- [ ] **Step 5: Run focused contract tests**

Run: `pytest tests/test_domain.py tests/test_extractor_router.py tests/test_workflow.py tests/test_local_pipeline.py -v`

Expected: all tests pass and existing web records remain `sourceType: web`.

- [ ] **Step 6: Regenerate the portable Python schema**

Run:

```powershell
python -c "from pathlib import Path; import json; from ai_digest.domain import SummaryRecord; Path('schemas/summary-v1.json').write_text(json.dumps(SummaryRecord.model_json_schema(by_alias=True), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')"
pytest tests/test_domain.py::test_portable_schema_matches_the_summary_record_contract -v
```

Expected: schema test passes and the enum for `sourceType` is `web`, `youtube`.

- [ ] **Step 7: Commit Task 2**

```powershell
git add -- src/ai_digest/domain.py src/ai_digest/workflow.py src/ai_digest/extractors/base.py src/ai_digest/extractors/router.py tests/test_domain.py tests/test_extractor_router.py tests/test_workflow.py schemas/summary-v1.json
git commit -m "refactor: route source extractors by type"
```

---

### Task 3: Caption Selection and VTT Normalization

**Files:**
- Create: `src/ai_digest/extractors/youtube_captions.py`
- Create: `tests/test_youtube_captions.py`
- Create: `tests/fixtures/youtube/captions-duplicate.vtt`

**Interfaces:**
- Produces: frozen `CaptionTrack(language: str, url: str, automatic: bool)`; `select_caption(manual, automatic, original_language) -> CaptionTrack | None`; `normalize_vtt(payload: str) -> str`.

- [ ] **Step 1: Write failing caption-selection tests**

```python
from ai_digest.extractors.youtube_captions import CaptionTrack, select_caption


def track(language: str, *, automatic: bool = False) -> CaptionTrack:
    return CaptionTrack(language=language, url=f"https://captions.example/{language}", automatic=automatic)


def test_prefers_manual_traditional_chinese_then_manual_original_language() -> None:
    manual = [track("en"), track("zh-Hant"), track("ja")]
    automatic = [track("zh-TW", automatic=True)]
    assert select_caption(manual, automatic, "ja") == manual[1]
    assert select_caption([track("en"), track("ja")], automatic, "ja").language == "ja"


def test_uses_automatic_only_when_no_manual_caption_is_available() -> None:
    automatic = [track("en", automatic=True), track("zh-TW", automatic=True)]
    assert select_caption([], automatic, "en") == automatic[1]
```

- [ ] **Step 2: Add a fixture and failing normalization test**

```text
WEBVTT

00:00:00.000 --> 00:00:02.000
<c>第一句</c>

00:00:01.500 --> 00:00:03.000
第一句

00:00:03.000 --> 00:00:05.000
第二句 &amp; 補充
```

```python
from pathlib import Path
from ai_digest.extractors.youtube_captions import normalize_vtt


def test_normalize_vtt_removes_markup_timestamps_and_consecutive_duplicates() -> None:
    payload = Path("tests/fixtures/youtube/captions-duplicate.vtt").read_text(encoding="utf-8")
    assert normalize_vtt(payload) == "第一句\n第二句 & 補充"
```

- [ ] **Step 3: Run caption tests and verify red**

Run: `pytest tests/test_youtube_captions.py -v`

Expected: import failure for the missing module.

- [ ] **Step 4: Implement caption selection and normalization**

```python
from dataclasses import dataclass
from html import unescape
import re


_TRADITIONAL = ("zh-TW", "zh-Hant", "zh-HK")
_TIMING = re.compile(r"^\s*\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->.*$")
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    language: str
    url: str
    automatic: bool


def _rank(track: CaptionTrack, original_language: str | None) -> tuple[int, str]:
    if track.language in _TRADITIONAL:
        return (0, track.language)
    if original_language and track.language == original_language:
        return (1, track.language)
    return (2, track.language)


def select_caption(
    manual: list[CaptionTrack], automatic: list[CaptionTrack], original_language: str | None
) -> CaptionTrack | None:
    candidates = manual if manual else automatic
    return min(candidates, key=lambda item: _rank(item, original_language), default=None)


def normalize_vtt(payload: str) -> str:
    normalized: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or _TIMING.match(line) or line.isdigit():
            continue
        text = unescape(_TAG.sub("", line)).strip()
        if text and (not normalized or normalized[-1] != text):
            normalized.append(text)
    return "\n".join(normalized)
```

- [ ] **Step 5: Run caption tests**

Run: `pytest tests/test_youtube_captions.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- src/ai_digest/extractors/youtube_captions.py tests/test_youtube_captions.py tests/fixtures/youtube/captions-duplicate.vtt
git commit -m "feat: select and normalize YouTube captions"
```

---

### Task 4: Safe Media Tool Boundary and Temporary File Cleanup

**Files:**
- Create: `src/ai_digest/extractors/youtube_media.py`
- Create: `tests/test_youtube_media.py`

**Interfaces:**
- Produces: `CommandRunner.run(argv: list[str]) -> CompletedProcess[str]`; `YouTubeMediaPipeline.audio_chunks(url: str, chunk_seconds: int) -> context manager yielding list[Path]`.
- The runner receives argument arrays only; no command string and no `shell=True` path exists.

- [ ] **Step 1: Write failing tests for safe argv and missing tools**

```python
import subprocess
from pathlib import Path

import pytest

from ai_digest.domain import DigestError
from ai_digest.extractors.youtube_media import CommandRunner


def test_command_runner_never_uses_a_shell(monkeypatch) -> None:
    observed = {}

    def fake_run(argv, **kwargs):
        observed.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    CommandRunner().run(["yt-dlp", "--version"])
    assert observed["argv"] == ["yt-dlp", "--version"]
    assert observed["kwargs"]["shell"] is False


def test_command_runner_maps_missing_executable_without_leaking_path(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("SECRET_PATH")))
    with pytest.raises(DigestError) as raised:
        CommandRunner().run(["yt-dlp", "--version"])
    assert raised.value.code == "MEDIA_TOOL_MISSING"
    assert "SECRET_PATH" not in raised.value.message
```

- [ ] **Step 2: Write failing cleanup test around the pipeline context manager**

```python
def test_audio_chunks_removes_isolated_directory_after_failure(tmp_path: Path) -> None:
    created = []

    class FailingRunner:
        def run(self, argv):
            created.append(Path(argv[argv.index("-P") + 1]))
            raise DigestError("extract", "MEDIA_DOWNLOAD_FAILED", "Media download failed", True)

    pipeline = YouTubeMediaPipeline(FailingRunner(), temp_root=tmp_path)
    with pytest.raises(DigestError):
        with pipeline.audio_chunks("https://www.youtube.com/watch?v=dQw4w9WgXcQ", 600):
            pass
    assert len(created) == 1
    assert not created[0].exists()
```

- [ ] **Step 3: Run media tests and verify red**

Run: `pytest tests/test_youtube_media.py -v`

Expected: import failure for the missing module.

- [ ] **Step 4: Implement runner and context-managed media pipeline**

```python
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import tempfile

from ai_digest.domain import DigestError


class CommandRunner:
    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv, shell=False, check=True, capture_output=True, text=True, timeout=300
            )
        except FileNotFoundError as error:
            raise DigestError("extract", "MEDIA_TOOL_MISSING", "Required media tool is unavailable", False) from error
        except subprocess.TimeoutExpired as error:
            raise DigestError("extract", "MEDIA_DOWNLOAD_FAILED", "Media tool timed out", True) from error
        except subprocess.CalledProcessError as error:
            raise DigestError("extract", "MEDIA_DOWNLOAD_FAILED", "Media download or conversion failed", True) from error


class YouTubeMediaPipeline:
    def __init__(self, runner: CommandRunner, temp_root: Path | None = None) -> None:
        self._runner = runner
        self._temp_root = temp_root

    @contextmanager
    def audio_chunks(self, url: str, chunk_seconds: int) -> Iterator[list[Path]]:
        directory = Path(tempfile.mkdtemp(prefix="ai-digest-youtube-", dir=self._temp_root))
        try:
            self._runner.run(["yt-dlp", "--no-playlist", "-f", "bestaudio", "-P", str(directory), "-o", "source.%(ext)s", url])
            source = next(directory.glob("source.*"), None)
            if source is None:
                raise DigestError("extract", "MEDIA_DOWNLOAD_FAILED", "Media download produced no audio", True)
            pattern = directory / "chunk-%04d.mp3"
            self._runner.run(["ffmpeg", "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-f", "segment", "-segment_time", str(chunk_seconds), str(pattern)])
            chunks = sorted(directory.glob("chunk-*.mp3"))
            if not chunks:
                raise DigestError("extract", "MEDIA_DOWNLOAD_FAILED", "Media conversion produced no audio", True)
            yield chunks
        finally:
            shutil.rmtree(directory, ignore_errors=True)
```

- [ ] **Step 5: Add success, nonzero-exit, timeout, empty-output, and `KeyboardInterrupt` cleanup tests**

```python
class CreatingRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv):
        self.calls.append(argv)
        directory = Path(argv[argv.index("-P") + 1]) if "-P" in argv else Path(argv[-1]).parent
        if argv[0] == "yt-dlp":
            (directory / "source.webm").write_bytes(b"source")
        else:
            (directory / "chunk-0001.mp3").write_bytes(b"second")
            (directory / "chunk-0000.mp3").write_bytes(b"first")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_audio_chunks_are_ordered_use_safe_flags_and_are_removed(tmp_path: Path) -> None:
    runner = CreatingRunner()
    pipeline = YouTubeMediaPipeline(runner, temp_root=tmp_path)
    with pipeline.audio_chunks("https://www.youtube.com/watch?v=dQw4w9WgXcQ", 600) as chunks:
        assert [item.name for item in chunks] == ["chunk-0000.mp3", "chunk-0001.mp3"]
    yt_dlp = runner.calls[0]
    assert "--no-playlist" in yt_dlp
    assert not any("cookie" in value.lower() or "proxy" in value.lower() for value in yt_dlp)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", [RuntimeError("stop"), KeyboardInterrupt()])
def test_audio_chunks_cleanup_when_consumer_is_interrupted(tmp_path: Path, failure: BaseException) -> None:
    pipeline = YouTubeMediaPipeline(CreatingRunner(), temp_root=tmp_path)
    with pytest.raises(type(failure)):
        with pipeline.audio_chunks("https://www.youtube.com/watch?v=dQw4w9WgXcQ", 600):
            raise failure
    assert list(tmp_path.iterdir()) == []
```

Add runner tests that make `subprocess.run` raise `TimeoutExpired` and `CalledProcessError`, and a pipeline test whose fake conversion produces no chunks; assert the exact codes and retryability shown in Step 4.

- [ ] **Step 6: Run focused media tests**

Run: `pytest tests/test_youtube_media.py -v`

Expected: all runner, argv, ordering, failure mapping, and cleanup tests pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- src/ai_digest/extractors/youtube_media.py tests/test_youtube_media.py
git commit -m "feat: add safe YouTube media pipeline"
```

---

### Task 5: Lazy OpenAI Audio Transcription

**Files:**
- Create: `src/ai_digest/transcribers/__init__.py`
- Create: `src/ai_digest/transcribers/openai.py`
- Create: `tests/test_openai_transcriber.py`

**Interfaces:**
- Produces: `AudioTranscriber.transcribe(chunks: list[Path]) -> str`; `OpenAIAudioTranscriber(client: OpenAI, model: str)`; `lazy_openai_transcriber(api_key: str | None, model: str) -> OpenAIAudioTranscriber`.

- [ ] **Step 1: Write failing tests for ordered merging and lazy missing-key handling**

```python
from pathlib import Path
import pytest

from ai_digest.domain import DigestError
from ai_digest.transcribers.openai import OpenAIAudioTranscriber, lazy_openai_transcriber


class FakeTranscriptions:
    def __init__(self):
        self.names = []

    def create(self, *, model, file):
        self.names.append(file.name)
        return type("Transcript", (), {"text": f"text:{file.name}"})()


def test_transcribes_chunks_in_order_and_merges_only_complete_result(tmp_path: Path) -> None:
    chunks = [tmp_path / "chunk-0000.mp3", tmp_path / "chunk-0001.mp3"]
    for chunk in chunks:
        chunk.write_bytes(b"audio")
    transcriptions = FakeTranscriptions()
    client = type("Client", (), {"audio": type("Audio", (), {"transcriptions": transcriptions})()})()

    result = OpenAIAudioTranscriber(client, "test-model").transcribe(chunks)

    assert transcriptions.names == ["chunk-0000.mp3", "chunk-0001.mp3"]
    assert result == "text:chunk-0000.mp3\ntext:chunk-0001.mp3"


def test_missing_key_is_reported_before_constructing_openai_client() -> None:
    with pytest.raises(DigestError) as raised:
        lazy_openai_transcriber(None, "gpt-transcribe")
    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "MISSING_API_KEY",
        "message": "OPENAI_API_KEY is required for YouTube audio transcription",
        "retryable": False,
    }
```

- [ ] **Step 2: Run transcription tests and verify red**

Run: `pytest tests/test_openai_transcriber.py -v`

Expected: import failure for the missing transcriber module.

- [ ] **Step 3: Implement the protocol, adapter, and safe error mapping**

```python
# src/ai_digest/transcribers/__init__.py
from pathlib import Path
from typing import Protocol


class AudioTranscriber(Protocol):
    def transcribe(self, chunks: list[Path]) -> str: ...
```

```python
# src/ai_digest/transcribers/openai.py
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from ai_digest.domain import DigestError


class OpenAIAudioTranscriber:
    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def transcribe(self, chunks: list[Path]) -> str:
        completed: list[str] = []
        for chunk in chunks:
            try:
                with chunk.open("rb") as audio:
                    result = self._client.audio.transcriptions.create(model=self._model, file=audio)
            except APITimeoutError as error:
                raise DigestError("extract", "TRANSCRIPTION_TIMEOUT", "Audio transcription timed out", True) from error
            except RateLimitError as error:
                raise DigestError("extract", "TRANSCRIPTION_RATE_LIMITED", "Audio transcription is rate limited", True) from error
            except APIConnectionError as error:
                raise DigestError("extract", "TRANSCRIPTION_FAILED", "Audio transcription request failed", True) from error
            except APIStatusError as error:
                raise DigestError("extract", "TRANSCRIPTION_FAILED", "Audio transcription request failed", error.status_code >= 500) from error
            text = getattr(result, "text", "").strip()
            if not text:
                raise DigestError("extract", "TRANSCRIPTION_FAILED", "Audio transcription returned no text", False)
            completed.append(text)
        return "\n".join(completed)


def lazy_openai_transcriber(api_key: str | None, model: str) -> OpenAIAudioTranscriber:
    if not api_key:
        raise DigestError("input", "MISSING_API_KEY", "OPENAI_API_KEY is required for YouTube audio transcription", False)
    return OpenAIAudioTranscriber(OpenAI(api_key=api_key), model)
```

- [ ] **Step 4: Add parameterized timeout, rate-limit, connection, 4xx, 5xx, and blank-result tests**

```python
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (APITimeoutError(httpx.Request("POST", "https://api.openai.com")), "TRANSCRIPTION_TIMEOUT", True),
        (RateLimitError("limited", response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")), body=None), "TRANSCRIPTION_RATE_LIMITED", True),
        (APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")), "TRANSCRIPTION_FAILED", True),
        (APIStatusError("bad", response=httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com")), body=None), "TRANSCRIPTION_FAILED", False),
        (APIStatusError("down", response=httpx.Response(503, request=httpx.Request("POST", "https://api.openai.com")), body=None), "TRANSCRIPTION_FAILED", True),
    ],
)
def test_maps_transcription_failures_to_safe_errors(tmp_path: Path, error: Exception, code: str, retryable: bool) -> None:
    chunk = tmp_path / "SECRET-chunk.mp3"
    chunk.write_bytes(b"SECRET_AUDIO")
    client = failing_client(error)
    with pytest.raises(DigestError) as raised:
        OpenAIAudioTranscriber(client, "test-model").transcribe([chunk])
    assert (raised.value.stage, raised.value.code, raised.value.retryable) == ("extract", code, retryable)
    assert "SECRET" not in raised.value.message


def test_rejects_blank_transcription(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    client = client_returning("   ")
    with pytest.raises(DigestError) as raised:
        OpenAIAudioTranscriber(client, "test-model").transcribe([chunk])
    assert (raised.value.code, raised.value.retryable) == ("TRANSCRIPTION_FAILED", False)
```

Define `failing_client(error)` and `client_returning(text)` in the test file as minimal nested objects exposing `audio.transcriptions.create`; the former raises the supplied exception and the latter returns an object with `.text`.

- [ ] **Step 5: Run transcription tests**

Run: `pytest tests/test_openai_transcriber.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 5**

```powershell
git add -- src/ai_digest/transcribers/__init__.py src/ai_digest/transcribers/openai.py tests/test_openai_transcriber.py
git commit -m "feat: transcribe YouTube audio with OpenAI"
```

---

### Task 6: YouTube Metadata, Captions-First Orchestration, and CLI Composition

**Files:**
- Create: `src/ai_digest/extractors/youtube.py`
- Create: `tests/test_youtube_extractor.py`
- Modify: `src/ai_digest/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `CaptionTrack`, `select_caption`, `normalize_vtt`, `YouTubeMediaPipeline.audio_chunks`, `AudioTranscriber.transcribe`, and `ExtractorRouter` from Tasks 2–5.
- Produces: `YouTubeExtractor(probe, caption_client, media, transcriber_factory, max_duration_seconds, chunk_seconds)` implementing `Extractor`.
- Probe contract: `probe(url: str) -> dict[str, object]` with `id`, `title`, `channel`, `upload_date`, `duration`, `live_status`, `availability`, `language`, `subtitles`, and `automatic_captions`.

- [ ] **Step 1: Write failing successful-caption orchestration test**

```python
from ai_digest.extractors.youtube import YouTubeExtractor


def public_metadata(**changes):
    value = {
        "id": "dQw4w9WgXcQ",
        "title": "公開影片",
        "channel": "公開頻道",
        "upload_date": "20260820",
        "duration": 120,
        "live_status": "not_live",
        "availability": "public",
        "language": "zh-TW",
        "subtitles": {"zh-TW": [{"url": "https://captions.example/manual.vtt", "ext": "vtt"}]},
        "automatic_captions": {},
    }
    value.update(changes)
    return value


def test_uses_caption_without_media_or_transcriber() -> None:
    calls = []
    extractor = YouTubeExtractor(
        probe=lambda url: public_metadata(),
        caption_client=lambda url: "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + "字幕內容" * 80,
        media=lambda: (_ for _ in ()).throw(AssertionError("media must not run")),
        transcriber_factory=lambda: (_ for _ in ()).throw(AssertionError("OpenAI must not run")),
        max_duration_seconds=7200,
        chunk_seconds=600,
    )

    article = extractor.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert article.source_type == "youtube"
    assert str(article.canonical_url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert article.title == "公開影片"
    assert article.author == "公開頻道"
    assert "字幕內容" in article.text
```

- [ ] **Step 2: Write failing no-caption lazy fallback test**

```python
from contextlib import contextmanager


def test_no_caption_lazily_transcribes_audio(tmp_path) -> None:
    events = []
    chunks = [tmp_path / "chunk-0000.mp3", tmp_path / "chunk-0001.mp3"]

    @contextmanager
    def media(url, chunk_seconds):
        events.append("media-enter")
        try:
            yield chunks
        finally:
            events.append("media-exit")

    class Transcriber:
        def transcribe(self, supplied):
            events.append("transcribe")
            assert supplied == chunks
            return "完整逐字稿" * 80

    def factory():
        events.append("transcriber-factory")
        return Transcriber()

    extractor = YouTubeExtractor(lambda url: events.append("probe") or public_metadata(subtitles={}, automatic_captions={}), lambda url: pytest.fail("caption client must not run"), media, factory, 7200, 600)
    article = extractor.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert events == ["probe", "media-enter", "transcriber-factory", "transcribe", "media-exit"]
    assert "完整逐字稿" in article.text
```

- [ ] **Step 3: Write failing restriction and safe-error tests**

```python
@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"availability": "private"}, "CONTENT_UNAVAILABLE"),
        ({"availability": "needs_auth"}, "LOGIN_REQUIRED"),
        ({"live_status": "is_live"}, "LIVE_STREAM_UNSUPPORTED"),
        ({"live_status": "is_upcoming"}, "LIVE_STREAM_UNSUPPORTED"),
        ({"duration": 7201}, "VIDEO_TOO_LONG"),
    ],
)
def test_rejects_restricted_live_and_long_videos_before_content_access(changes, code) -> None:
    forbidden = lambda *args: pytest.fail("content stage must not run")
    extractor = YouTubeExtractor(lambda url: public_metadata(**changes), forbidden, forbidden, forbidden, 7200, 600)
    with pytest.raises(DigestError) as raised:
        extractor.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert (raised.value.stage, raised.value.code, raised.value.retryable) == ("extract", code, False)
    assert "dQw4w9WgXcQ" not in raised.value.message
```

Parameterize metadata for private/members-only/unavailable, login/age-gated, `is_live`/`is_upcoming`, and duration `7201`; assert respectively `CONTENT_UNAVAILABLE`, `LOGIN_REQUIRED`, `LIVE_STREAM_UNSUPPORTED`, and `VIDEO_TOO_LONG`, all non-retryable. Assert neither captions, media, nor OpenAI is called and no metadata URL/title/raw probe error is exposed.

- [ ] **Step 4: Run YouTube extractor tests and verify red**

Run: `pytest tests/test_youtube_extractor.py -v`

Expected: import failure for the missing extractor module.

- [ ] **Step 5: Implement YouTube extractor orchestration**

```python
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle
from ai_digest.extractors.youtube_captions import CaptionTrack, normalize_vtt, select_caption
from ai_digest.transcribers import AudioTranscriber


_MIN_TEXT_LENGTH = 200


class YouTubeExtractor:
    def __init__(
        self,
        probe: Callable[[str], dict[str, Any]],
        caption_client: Callable[[str], str],
        media: Callable[[str, int], AbstractContextManager[list[Path]]],
        transcriber_factory: Callable[[], AudioTranscriber],
        max_duration_seconds: int,
        chunk_seconds: int,
    ) -> None:
        self._probe = probe
        self._caption_client = caption_client
        self._media = media
        self._transcriber_factory = transcriber_factory
        self._max_duration = max_duration_seconds
        self._chunk_seconds = chunk_seconds

    def extract(self, url: str) -> ExtractedArticle:
        metadata = self._safe_probe(url)
        self._validate_availability(metadata)
        track = select_caption(
            self._tracks(metadata.get("subtitles"), automatic=False),
            self._tracks(metadata.get("automatic_captions"), automatic=True),
            metadata.get("language") if isinstance(metadata.get("language"), str) else None,
        )
        if track is not None:
            text = normalize_vtt(self._caption_client(track.url))
        else:
            with self._media(url, self._chunk_seconds) as chunks:
                text = self._transcriber_factory().transcribe(chunks)
        if len(text) < _MIN_TEXT_LENGTH:
            raise DigestError("extract", "INSUFFICIENT_TEXT", "YouTube source does not contain enough text", False)
        try:
            return ExtractedArticle(
                canonicalUrl=url,
                sourceType="youtube",
                title=metadata["title"],
                author=metadata.get("channel"),
                publishedAt=self._published_at(metadata.get("upload_date")),
                text=text,
            )
        except (KeyError, TypeError, ValidationError) as error:
            raise DigestError("extract", "INVALID_METADATA", "YouTube metadata is invalid", False) from error
```

Add these methods to the class:

```python
    def _safe_probe(self, url: str) -> dict[str, Any]:
        try:
            return self._probe(url)
        except DigestError:
            raise
        except Exception as error:
            raise DigestError("extract", "MEDIA_DOWNLOAD_FAILED", "YouTube metadata request failed", True) from error

    def _validate_availability(self, metadata: dict[str, Any]) -> None:
        availability = metadata.get("availability")
        if availability in {"needs_auth", "needs_subscription"}:
            raise DigestError("extract", "LOGIN_REQUIRED", "YouTube source requires login", False)
        if availability not in {None, "public", "unlisted"}:
            raise DigestError("extract", "CONTENT_UNAVAILABLE", "YouTube source is unavailable", False)
        if metadata.get("live_status") in {"is_live", "is_upcoming"}:
            raise DigestError("extract", "LIVE_STREAM_UNSUPPORTED", "Live YouTube sources are unsupported", False)
        duration = metadata.get("duration")
        if not isinstance(duration, (int, float)) or duration < 0:
            raise DigestError("extract", "INVALID_METADATA", "YouTube metadata is invalid", False)
        if duration > self._max_duration:
            raise DigestError("extract", "VIDEO_TOO_LONG", "YouTube video exceeds the duration limit", False)

    @staticmethod
    def _tracks(raw: object, *, automatic: bool) -> list[CaptionTrack]:
        if not isinstance(raw, dict):
            return []
        tracks = []
        for language, entries in raw.items():
            if not isinstance(language, str) or not isinstance(entries, list):
                continue
            entry = next((item for item in entries if isinstance(item, dict) and item.get("ext") == "vtt" and isinstance(item.get("url"), str)), None)
            if entry is not None:
                tracks.append(CaptionTrack(language, entry["url"], automatic))
        return tracks

    @staticmethod
    def _published_at(raw: object) -> datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
```

- [ ] **Step 6: Add a concrete yt-dlp metadata probe and caption HTTP adapter**

Add `YtDlpMetadataProbe` to `youtube.py`:

```python
class YtDlpMetadataProbe:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def __call__(self, url: str) -> dict[str, Any]:
        result = self._runner.run(["yt-dlp", "--dump-single-json", "--skip-download", "--no-playlist", url])
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as error:
            raise DigestError("extract", "INVALID_METADATA", "YouTube metadata is invalid", False) from error
        if not isinstance(value, dict):
            raise DigestError("extract", "INVALID_METADATA", "YouTube metadata is invalid", False)
        return value
```

Create a `YouTubeCaptionClient` beside it that reuses a refactored public-destination downloader extracted from `web.py`, with `max_bytes=2 * 1024 * 1024`, `max_redirects=3`, and `timeout=15.0`. Its `__call__(url: str) -> str` must accept only `text/vtt` or `text/plain`, decode UTF-8 with replacement, and map private redirects to `UNSAFE_DESTINATION`, over-limit bodies to `RESPONSE_TOO_LARGE`, timeouts to retryable `NETWORK_TIMEOUT`, and other HTTP failures consistently with `WebExtractor`. Add one focused test per mapping using `httpx.MockTransport`; no real caption request is permitted.

- [ ] **Step 7: Wire lazy production dependencies in CLI**

Add validated integer settings:

```python
def _positive_int_setting(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise DigestError("input", "INVALID_CONFIG", f"{name} must be a positive integer", False) from error
    if value <= 0:
        raise DigestError("input", "INVALID_CONFIG", f"{name} must be a positive integer", False)
    return value
```

Compose production dependencies as follows (adapt constructor names only if the implementation established in Step 6 differs):

```python
def _workflow(on_progress: Callable[[str], None] | None = None) -> AddArticleWorkflow:
    runner = CommandRunner()
    media = YouTubeMediaPipeline(runner)
    model = os.environ.get("AI_DIGEST_TRANSCRIPTION_MODEL", "gpt-transcribe")
    chunk_seconds = _positive_int_setting("AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", 600)
    youtube = YouTubeExtractor(
        probe=YtDlpMetadataProbe(runner),
        caption_client=YouTubeCaptionClient(client_factory=_web_client_factory),
        media=media.audio_chunks,
        transcriber_factory=lambda: lazy_openai_transcriber(os.environ.get("OPENAI_API_KEY"), model),
        max_duration_seconds=_positive_int_setting("AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS", 7200),
        chunk_seconds=chunk_seconds,
    )
    return AddArticleWorkflow(
        extractor=ExtractorRouter(WebExtractor(client_factory=_web_client_factory), youtube),
        summarizer=_summarizer(),
        classifier=_classifier(),
        repository=_repository(),
        on_progress=on_progress,
    )
```

In `tests/test_cli.py`, monkeypatch the new constructors and environment to assert defaults, parameterize `"0"`, `"-1"`, and `"abc"` as `INVALID_CONFIG`, execute a captioned Gemini workflow with no `OPENAI_API_KEY`, and invoke the no-caption transcriber factory directly to assert `MISSING_API_KEY` occurs before the fake media runner records a download.

- [ ] **Step 8: Run focused YouTube, CLI, and workflow tests**

Run: `pytest tests/test_youtube_extractor.py tests/test_cli.py tests/test_workflow.py tests/test_local_pipeline.py -v`

Expected: all tests pass without external binaries, network, or API keys.

- [ ] **Step 9: Commit Task 6**

```powershell
git add -- src/ai_digest/extractors/youtube.py src/ai_digest/cli.py tests/test_youtube_extractor.py tests/test_cli.py
git commit -m "feat: ingest public YouTube videos"
```

---

### Task 7: Frontend Contract, Documentation, and Milestone Verification

**Files:**
- Modify: `site/src/lib/summaries.ts`
- Modify: `site/src/lib/summary-loader.ts`
- Modify: `site/src/lib/summaries.test.ts`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: portable schema and `sourceType: "web" | "youtube"` contract from Task 2.
- Produces: Astro loader accepts verified published YouTube records; documented local tool/config requirements and truthful milestone status.

- [ ] **Step 1: Write a failing frontend contract test**

Add a published YouTube record fixture to `site/src/lib/summaries.test.ts`:

```typescript
it('loads a published YouTube summary', async () => {
  const record = validRecord({
    canonicalUrl: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    sourceType: 'youtube',
    title: '公開影片',
  });
  const loaded = await loadSummariesFromValues([record]);
  expect(loaded).toHaveLength(1);
  expect(loaded[0].sourceType).toBe('youtube');
});
```

- [ ] **Step 2: Run the focused frontend test and verify red**

Run: `npm.cmd test -- --run site/src/lib/summaries.test.ts` from `site` (if Vitest path resolution rejects the prefixed path, use `npm.cmd test -- --run src/lib/summaries.test.ts`).

Expected: Zod rejects `sourceType: youtube`.

- [ ] **Step 3: Expand TypeScript and Zod source type contracts**

```typescript
// site/src/lib/summaries.ts
sourceType: 'web' | 'youtube';

// site/src/lib/summary-loader.ts
sourceType: z.enum(['web', 'youtube']),
```

- [ ] **Step 4: Run frontend tests and production build**

Run from `site`:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: all Vitest tests pass; `astro check` reports zero errors and Astro production build exits zero.

- [ ] **Step 5: Document local requirements and safe settings**

Add only placeholders/defaults to `.env.example`:

```dotenv
# Needed only when a YouTube video has no usable captions.
AI_DIGEST_TRANSCRIPTION_MODEL=gpt-transcribe
AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS=600
AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS=7200
```

In `README.md`, document installing `yt-dlp` and FFmpeg on `PATH`, captions-first behavior, the two-hour default, lazy `OPENAI_API_KEY`, unsupported source states, and that no cookies/access bypass are supported. Do not include a real key, cookie, transcript, or real local path.

- [ ] **Step 6: Run the complete automated verification**

Run from repository root:

```powershell
pytest
Push-Location site
npm.cmd test
npm.cmd run build
Pop-Location
git diff --check
```

Expected: complete Python suite passes; complete Vitest suite passes; Astro check/build exits zero; diff check exits zero.

- [ ] **Step 7: Validate data and scan tracked/build output for secrets or media**

Run:

```powershell
pytest tests/test_domain.py::test_portable_schema_matches_the_summary_record_contract tests/test_storage.py -v
git grep -n -I -E "sk-[A-Za-z0-9_-]{20,}|OPENAI_API_KEY=.+|Cookie:" -- . ':!*.example'
Get-ChildItem -Path site/dist -Recurse -File | Where-Object { $_.Extension -in '.mp3','.m4a','.webm','.vtt','.srt' }
```

Expected: schema/storage tests pass; grep returns no matches (exit 1 is the expected no-match result); build scan prints no media/caption files.

- [ ] **Step 8: Perform two short real-video smoke checks when prerequisites exist**

Confirm `yt-dlp --version`, `ffmpeg -version`, network access, and required API keys without printing secret values. Run `ai-digest add` against one short public captioned video and one short public no-caption video chosen at execution time. Verify each saved JSON passes `SummaryRecord.model_validate_json`, uses canonical `watch?v=` URL, has `sourceType: youtube`, and contains no local path or transcript artifact.

If any prerequisite is missing or either external source has changed, do not mark this step complete. Record the exact unverified check and reason in `progress.md`; never weaken tests or substitute a restricted video.

- [ ] **Step 9: Update progress and todo truthfully**

In `progress.md`, record automated command results, counts, smoke-test URLs only if safe to publish, external tool versions, known risks, blockers, decisions, and the next milestone. In `todo.md`, check only YouTube behaviors proven by the completed automated and manual validation; leave no-caption integration unchecked if Step 8 could not run.

- [ ] **Step 10: Review and commit the milestone**

Run `git status --short` and `git diff --name-only`; ensure unrelated proposal documents and pre-existing untracked files are absent from staging. Then:

```powershell
git add -- site/src/lib/summaries.ts site/src/lib/summary-loader.ts site/src/lib/summaries.test.ts .env.example README.md progress.md todo.md
git commit -m "docs: record YouTube source milestone"
```

Do not push, create a PR, or deploy unless the user explicitly authorizes that remote action at execution time.

---

## Final Review Gate

- Confirm every design requirement in `docs/superpowers/specs/2026-08-21-youtube-source-design.md` maps to a completed task above.
- Request a fresh code review after Task 6 and again after Task 7 if review feedback changes behavior.
- Re-run the complete verification after any review fix.
- Inspect `git status --short`, the commit list, and all staged paths before any remote push.
