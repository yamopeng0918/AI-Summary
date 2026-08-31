"""Local command-line interface for AI Digest."""

from collections.abc import Callable
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Literal, TextIO
from zoneinfo import ZoneInfo

import httpx
import typer
from google import genai
from openai import OpenAI

from ai_digest.classifiers.base import Classifier
from ai_digest.classifiers.service import ClassifierEvaluationService
from ai_digest.classifiers.trained import TrainedClassifier
from ai_digest.domain import DigestError, SummaryRecord
from ai_digest.editing import EditorRunner, EditSummaryWorkflow
from ai_digest.extractors.bluesky import BlueskyAppViewClient, BlueskyExtractor
from ai_digest.extractors.router import ExtractorRouter, LazyExtractor
from ai_digest.extractors.web import WebExtractor
from ai_digest.extractors.youtube import (
    YouTubeCaptionClient,
    YouTubeExtractor,
    YtDlpMetadataProbe,
)
from ai_digest.extractors.youtube_media import CommandRunner, YouTubeMediaPipeline
from ai_digest.regeneration import RegenerateSummaryWorkflow
from ai_digest.storage import SummaryRepository
from ai_digest.summarizers.base import Summarizer
from ai_digest.summarizers.gemini import GeminiSummarizer
from ai_digest.summarizers.openai import OpenAISummarizer
from ai_digest.transcribers import AudioTranscriber
from ai_digest.transcribers.gemini import lazy_gemini_transcriber
from ai_digest.transcribers.openai import lazy_openai_transcriber
from ai_digest.workflow import AddArticleWorkflow


_TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> datetime:
    return datetime.now(_TAIPEI)


def _repository() -> SummaryRepository:
    return SummaryRepository(Path(os.environ.get("AI_DIGEST_SUMMARY_ROOT", "data/summaries")))


def _web_client_factory() -> httpx.Client:
    return httpx.Client()


def _classifier() -> Classifier:
    return TrainedClassifier(
        Path("models/classifier.joblib"),
        Path("models/classifier-manifest.json"),
        tuple(json.loads(Path("data/categories.json").read_text(encoding="utf-8"))),
    )


def _provider() -> Literal["gemini", "openai"]:
    provider = os.environ.get("AI_DIGEST_PROVIDER", "gemini").strip().lower()
    if provider not in {"gemini", "openai"}:
        raise DigestError(
            "input", "INVALID_PROVIDER", "AI_DIGEST_PROVIDER must be gemini or openai", False
        )
    return provider


def _summarizer(provider: Literal["gemini", "openai"]) -> Summarizer:
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise DigestError("input", "MISSING_API_KEY", "GEMINI_API_KEY is required for add", False)
        return GeminiSummarizer(
            genai.Client(api_key=api_key), os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        )
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise DigestError("input", "MISSING_API_KEY", "OPENAI_API_KEY is required for add", False)
    return OpenAISummarizer(OpenAI(api_key=api_key), os.environ.get("OPENAI_MODEL", "gpt-5-mini"))


def _transcriber_factory(
    provider: Literal["gemini", "openai"],
) -> Callable[[], AudioTranscriber]:
    if provider == "gemini":
        return lambda: lazy_gemini_transcriber(
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GEMINI_TRANSCRIPTION_MODEL", "gemini-3.6-flash"),
        )
    return lambda: lazy_openai_transcriber(
        os.environ.get("OPENAI_API_KEY"),
        os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe"),
    )


def _positive_int_setting(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise DigestError(
            "input",
            "INVALID_CONFIG",
            f"{name} must be a positive integer",
            False,
        ) from None
    if value <= 0:
        raise DigestError(
            "input",
            "INVALID_CONFIG",
            f"{name} must be a positive integer",
            False,
        )
    return value


def _youtube_extractor(provider: Literal["gemini", "openai"]) -> YouTubeExtractor:
    runner = CommandRunner()
    media = YouTubeMediaPipeline(
        runner,
        max_chunk_bytes=_positive_int_setting(
            "AI_DIGEST_TRANSCRIPTION_MAX_CHUNK_BYTES", 24 * 1024 * 1024
        ),
    )
    chunk_seconds = _positive_int_setting(
        "AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS", 600
    )
    return YouTubeExtractor(
        probe=YtDlpMetadataProbe(runner),
        caption_client=YouTubeCaptionClient(client_factory=_web_client_factory),
        media=media.audio_chunks,
        transcriber_factory=_transcriber_factory(provider),
        max_duration_seconds=_positive_int_setting(
            "AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS", 7200
        ),
        chunk_seconds=chunk_seconds,
    )


def _workflow(on_progress: Callable[[str], None] | None = None) -> AddArticleWorkflow:
    provider = _provider()
    return AddArticleWorkflow(
        extractor=ExtractorRouter(
            WebExtractor(client_factory=_web_client_factory),
            LazyExtractor(lambda: _youtube_extractor(provider)),
            BlueskyExtractor(BlueskyAppViewClient(client_factory=_web_client_factory)),
        ),
        summarizer=_summarizer(provider),
        classifier=_classifier(),
        repository=_repository(),
        on_progress=on_progress,
    )


def _editor_runner() -> EditorRunner:
    return EditorRunner(os.environ, platform=sys.platform, command_runner=subprocess.run)


def _edit_workflow() -> EditSummaryWorkflow:
    return EditSummaryWorkflow(_repository(), _editor_runner(), _now)


def _regenerate_workflow(
    on_progress: Callable[[str], None] | None = None,
    *,
    repository_factory: Callable[[], SummaryRepository] | None = None,
) -> RegenerateSummaryWorkflow:
    provider = _provider()
    selected_repository_factory = _repository if repository_factory is None else repository_factory
    return RegenerateSummaryWorkflow(
        extractor=ExtractorRouter(
            WebExtractor(client_factory=_web_client_factory),
            LazyExtractor(lambda: _youtube_extractor(provider)),
            BlueskyExtractor(BlueskyAppViewClient(client_factory=_web_client_factory)),
        ),
        summarizer=_summarizer(provider),
        classifier=_classifier(),
        repository=selected_repository_factory(),
        on_progress=on_progress,
    )


def _evaluation_service() -> ClassifierEvaluationService:
    return ClassifierEvaluationService(clock=_now)


def _emit(payload: dict[str, object], *, err: bool = False) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=True), err=err)


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


def create_app(
    workflow_factory: Callable[[Callable[[str], None]], AddArticleWorkflow],
    repository_factory: Callable[[], SummaryRepository],
    clock: Callable[[], datetime],
    evaluation_service_factory: Callable[[], ClassifierEvaluationService] | None = None,
    edit_workflow_factory: Callable[[], EditSummaryWorkflow] | None = None,
    regenerate_workflow_factory: Callable[
        [Callable[[str], None]], RegenerateSummaryWorkflow
    ]
    | None = None,
) -> typer.Typer:
    """Create the CLI with dependencies supplied by the caller."""
    application = typer.Typer(no_args_is_help=True)
    evaluation_factory = evaluation_service_factory
    if evaluation_factory is None:
        evaluation_factory = lambda: ClassifierEvaluationService(clock=clock)
    edit_factory = edit_workflow_factory
    if edit_factory is None:
        edit_factory = lambda: EditSummaryWorkflow(repository_factory(), _editor_runner(), clock)
    regenerate_factory = regenerate_workflow_factory
    if regenerate_factory is None:
        regenerate_factory = lambda on_progress: _regenerate_workflow(
            on_progress, repository_factory=repository_factory
        )

    def report_error(error: DigestError) -> None:
        _emit(error.as_dict(), err=True)
        raise typer.Exit(code=1)

    @application.command()
    def add(url: str) -> None:
        """Extract, summarize, classify, and save one public article URL."""
        try:
            record = workflow_factory(lambda stage: _emit({"stage": stage})).run(url, clock())
            path = repository_factory().root / f"{record.id}.json"
            _emit({"stage": "complete", "id": record.id, "path": str(path)})
        except DigestError as error:
            report_error(error)

    @application.command()
    def edit(record_id: str) -> None:
        """Edit one locally stored summary in a configured text editor."""
        try:
            record = edit_factory().run(record_id)
            path = repository_factory().root / f"{record.id}.json"
            _emit({"stage": "complete", "id": record.id, "path": str(path)})
        except DigestError as error:
            report_error(error)

    @application.command()
    def regenerate(record_id: str) -> None:
        """Regenerate one stored summary from its public source."""
        try:
            workflow = regenerate_factory(lambda stage: _emit({"stage": stage}))
            record = workflow.run(record_id, clock())
            path = repository_factory().root / f"{record.id}.json"
            _emit({"stage": "complete", "id": record.id, "path": str(path)})
        except DigestError as error:
            report_error(error)

    @application.command("list")
    def list_records() -> None:
        """List locally stored summaries."""
        try:
            for record in repository_factory().list():
                typer.echo(f"{record.id}\t{record.title}\t{record.category}\t{record.status}")
        except DigestError as error:
            report_error(error)

    @application.command()
    def show(record_id: str) -> None:
        """Print one stored summary as JSON."""
        try:
            record = repository_factory().get(record_id)
            typer.echo(json.dumps(record.model_dump(mode="json", by_alias=True), ensure_ascii=False))
        except DigestError as error:
            report_error(error)

    def set_status(record_id: str, status: str) -> None:
        try:
            record = repository_factory().set_status(record_id, status, clock())  # type: ignore[arg-type]
            _emit({"id": record.id, "status": record.status})
        except DigestError as error:
            report_error(error)

    @application.command()
    def archive(record_id: str) -> None:
        """Archive one summary without deleting its content."""
        set_status(record_id, "archived")

    @application.command()
    def publish(record_id: str) -> None:
        """Publish one previously archived summary."""
        set_status(record_id, "published")

    @application.command("evaluate-classifier")
    def evaluate_classifier() -> None:
        """Evaluate reviewed classifier data and promote an accepted model."""
        try:
            service = evaluation_factory()
            result = service.run()
            _emit(service.cli_payload(result))
        except DigestError as error:
            report_error(error)

    return application


app = create_app(
    _workflow,
    _repository,
    _now,
    edit_workflow_factory=_edit_workflow,
    regenerate_workflow_factory=_regenerate_workflow,
)


def main() -> None:
    _configure_windows_utf8(sys.stdout, platform=sys.platform)
    _configure_windows_utf8(sys.stderr, platform=sys.platform)
    app()
