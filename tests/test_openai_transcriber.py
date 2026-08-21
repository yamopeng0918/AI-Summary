"""Tests for the OpenAI audio transcription boundary."""

from pathlib import Path
from types import SimpleNamespace
import traceback

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from ai_digest.domain import DigestError
from ai_digest.transcribers import openai as openai_transcriber
from ai_digest.transcribers.openai import OpenAIAudioTranscriber, lazy_openai_transcriber


class FakeTranscriptions:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.names: list[str] = []

    def create(self, *, model: str, file: object) -> object:
        self.names.append(Path(file.name).name)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


def client_with(outcomes: list[object]) -> tuple[object, FakeTranscriptions]:
    transcriptions = FakeTranscriptions(outcomes)
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    return client, transcriptions


def make_chunk(tmp_path: Path, name: str = "chunk.mp3") -> Path:
    chunk = tmp_path / name
    chunk.write_bytes(b"audio")
    return chunk


def rendered_exception(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_transcribes_chunks_in_order_and_merges_only_complete_result(tmp_path: Path) -> None:
    chunks = [make_chunk(tmp_path, "chunk-0000.mp3"), make_chunk(tmp_path, "chunk-0001.mp3")]
    client, transcriptions = client_with(["text:chunk-0000.mp3", "text:chunk-0001.mp3"])

    result = OpenAIAudioTranscriber(client, "test-model").transcribe(chunks)

    assert transcriptions.names == ["chunk-0000.mp3", "chunk-0001.mp3"]
    assert result == "text:chunk-0000.mp3\ntext:chunk-0001.mp3"


def test_missing_key_is_reported_before_constructing_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_constructed(**kwargs: object) -> object:
        raise AssertionError("OpenAI client must not be constructed")

    monkeypatch.setattr(openai_transcriber, "OpenAI", fail_if_constructed)

    with pytest.raises(DigestError) as raised:
        lazy_openai_transcriber(None, "gpt-transcribe")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "MISSING_API_KEY",
        "message": "OPENAI_API_KEY is required for YouTube audio transcription",
        "retryable": False,
    }


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            APITimeoutError(httpx.Request("POST", "https://api.openai.com")),
            "TRANSCRIPTION_TIMEOUT",
            True,
        ),
        (
            RateLimitError(
                "rate limit secret",
                response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "TRANSCRIPTION_RATE_LIMITED",
            True,
        ),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.com"),
                message="connection secret",
            ),
            "TRANSCRIPTION_FAILED",
            True,
        ),
        (
            APIStatusError(
                "bad request secret",
                response=httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "TRANSCRIPTION_FAILED",
            False,
        ),
        (
            APIStatusError(
                "service unavailable secret",
                response=httpx.Response(503, request=httpx.Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "TRANSCRIPTION_FAILED",
            True,
        ),
    ],
)
def test_maps_transcription_failures_to_safe_errors(
    tmp_path: Path, error: Exception, code: str, retryable: bool
) -> None:
    chunk = make_chunk(tmp_path, "SECRET-chunk.mp3")
    client, _ = client_with([error])

    with pytest.raises(DigestError) as raised:
        OpenAIAudioTranscriber(client, "test-model").transcribe([chunk])

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        code,
        retryable,
    )
    assert "SECRET" not in raised.value.message
    assert "secret" not in raised.value.message
    assert "SECRET-chunk.mp3" not in rendered_exception(raised.value)
    assert "secret" not in rendered_exception(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


def test_rejects_blank_transcription(tmp_path: Path) -> None:
    chunk = make_chunk(tmp_path)
    client, _ = client_with(["   "])

    with pytest.raises(DigestError) as raised:
        OpenAIAudioTranscriber(client, "test-model").transcribe([chunk])

    assert (raised.value.code, raised.value.retryable) == ("TRANSCRIPTION_FAILED", False)
    assert raised.value.__cause__ is None


def test_chunk_failure_does_not_return_partial_transcript(tmp_path: Path) -> None:
    chunks = [make_chunk(tmp_path, "chunk-0000.mp3"), make_chunk(tmp_path, "chunk-0001.mp3")]
    timeout = APITimeoutError(httpx.Request("POST", "https://api.openai.com"))
    client, transcriptions = client_with(["first complete chunk", timeout])

    with pytest.raises(DigestError) as raised:
        OpenAIAudioTranscriber(client, "test-model").transcribe(chunks)

    assert raised.value.code == "TRANSCRIPTION_TIMEOUT"
    assert transcriptions.names == ["chunk-0000.mp3", "chunk-0001.mp3"]
