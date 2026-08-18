"""Local command-line interface for AI Digest."""

from collections.abc import Callable
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import typer
from google import genai
from openai import OpenAI

from ai_digest.classifiers.fixed import FixedClassifier
from ai_digest.classifiers.service import ClassifierEvaluationService
from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES
from ai_digest.extractors.web import WebExtractor
from ai_digest.storage import SummaryRepository
from ai_digest.summarizers.base import Summarizer
from ai_digest.summarizers.gemini import GeminiSummarizer
from ai_digest.summarizers.openai import OpenAISummarizer
from ai_digest.workflow import AddArticleWorkflow


_TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> datetime:
    return datetime.now(_TAIPEI)


def _repository() -> SummaryRepository:
    return SummaryRepository(Path(os.environ.get("AI_DIGEST_SUMMARY_ROOT", "data/summaries")))


def _web_client_factory() -> httpx.Client:
    return httpx.Client()


def _summarizer() -> Summarizer:
    provider = os.environ.get("AI_DIGEST_PROVIDER", "gemini").strip().lower()
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise DigestError("input", "MISSING_API_KEY", "GEMINI_API_KEY is required for add", False)
        return GeminiSummarizer(
            genai.Client(api_key=api_key), os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        )
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise DigestError("input", "MISSING_API_KEY", "OPENAI_API_KEY is required for add", False)
        return OpenAISummarizer(OpenAI(api_key=api_key), os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    raise DigestError("input", "INVALID_PROVIDER", "AI_DIGEST_PROVIDER must be gemini or openai", False)


def _workflow(on_progress: Callable[[str], None] | None = None) -> AddArticleWorkflow:
    return AddArticleWorkflow(
        extractor=WebExtractor(client_factory=_web_client_factory),
        summarizer=_summarizer(),
        classifier=FixedClassifier(sorted(VALID_CATEGORIES)[0]),
        repository=_repository(),
        on_progress=on_progress,
    )


def _evaluation_service() -> ClassifierEvaluationService:
    return ClassifierEvaluationService(clock=_now)


def _emit(payload: dict[str, object], *, err: bool = False) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False), err=err)


def create_app(
    workflow_factory: Callable[[Callable[[str], None]], AddArticleWorkflow],
    repository_factory: Callable[[], SummaryRepository],
    clock: Callable[[], datetime],
    evaluation_service_factory: Callable[[], ClassifierEvaluationService] | None = None,
) -> typer.Typer:
    """Create the CLI with dependencies supplied by the caller."""
    application = typer.Typer(no_args_is_help=True)
    evaluation_factory = evaluation_service_factory or _evaluation_service

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


app = create_app(_workflow, _repository, _now)
