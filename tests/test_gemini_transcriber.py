from pathlib import Path
from types import SimpleNamespace
import traceback

import httpx
import pytest
from google.genai import errors

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
        outcome = next(self.responses)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


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


def make_chunk(root: Path, name: str) -> Path:
    chunk = root / name
    chunk.write_bytes(b"audio")
    return chunk


def rendered_exception(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


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
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=FakeFiles(events),
        models=FakeModels(
            events,
            [SimpleNamespace(text="第一段逐字稿"), SimpleNamespace(text="第二段逐字稿")],
        ),
    )
    chunks = [make_chunk(tmp_path, "chunk-0000.mp3"), make_chunk(tmp_path, "chunk-0001.mp3")]

    result = GeminiAudioTranscriber(
        client, "gemini-3.6-flash", sleeper=sleeps.append
    ).transcribe(chunks)

    assert result == "第一段逐字稿\n第二段逐字稿"
    assert events == [
        ("upload", "chunk-0000.mp3"),
        ("generate", "gemini-3.6-flash:files/chunk-1"),
        ("delete", "files/chunk-1"),
        ("upload", "chunk-0001.mp3"),
        ("generate", "gemini-3.6-flash:files/chunk-2"),
        ("delete", "files/chunk-2"),
    ]
    assert sleeps == []


from ai_digest.transcribers import AudioTranscriber


def accepts_transcriber(value: AudioTranscriber) -> AudioTranscriber:
    return value


def test_gemini_transcriber_satisfies_audio_transcriber_contract() -> None:
    client = SimpleNamespace(files=object(), models=object())
    assert accepts_transcriber(GeminiAudioTranscriber(client, "model")) is not None


@pytest.mark.parametrize("invalid_text", [None, 123, "", "   "])
def test_invalid_response_is_rejected_safely(tmp_path: Path, invalid_text: object) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=FakeFiles(events),
        models=FakeModels(events, [SimpleNamespace(text=invalid_text)]),
    )

    with pytest.raises(DigestError) as raised:
        GeminiAudioTranscriber(client, "test-model").transcribe([make_chunk(tmp_path, "chunk.mp3")])

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "TRANSCRIPTION_FAILED",
        "message": "Audio transcription response is invalid",
        "retryable": False,
    }
    assert raised.value.__cause__ is None


def test_partial_transcript_is_not_returned_when_later_response_is_blank(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=FakeFiles(events),
        models=FakeModels(
            events,
            [SimpleNamespace(text="first complete chunk"), SimpleNamespace(text="   ")],
        ),
    )
    chunks = [make_chunk(tmp_path, "chunk-0000.mp3"), make_chunk(tmp_path, "chunk-0001.mp3")]

    with pytest.raises(DigestError):
        GeminiAudioTranscriber(client, "test-model").transcribe(chunks)

    assert [event for event in events if event[0] == "delete"] == [
        ("delete", "files/chunk-1"),
        ("delete", "files/chunk-2"),
    ]


@pytest.mark.parametrize(
    ("error", "code", "message", "retryable"),
    [
        (
            httpx.TimeoutException("SECRET"),
            "TRANSCRIPTION_TIMEOUT",
            "Audio transcription timed out",
            True,
        ),
        (
            httpx.TransportError("SECRET"),
            "TRANSCRIPTION_FAILED",
            "Audio transcription request failed",
            True,
        ),
        (
            errors.ClientError(429, {"message": "SECRET"}, None),
            "TRANSCRIPTION_RATE_LIMITED",
            "Audio transcription is rate limited",
            True,
        ),
        (
            errors.ClientError(400, {"message": "SECRET"}, None),
            "TRANSCRIPTION_FAILED",
            "Audio transcription request failed",
            False,
        ),
        (
            errors.ServerError(503, {"message": "SECRET"}, None),
            "TRANSCRIPTION_FAILED",
            "Audio transcription request failed",
            True,
        ),
        (
            errors.UnknownApiResponseError(200, {"message": "SECRET"}, None),
            "TRANSCRIPTION_FAILED",
            "Audio transcription request failed",
            False,
        ),
        (
            OSError("SECRET C:\\private\\chunk.mp3"),
            "TRANSCRIPTION_FAILED",
            "Audio transcription request failed",
            False,
        ),
        (
            RuntimeError("SECRET files/private"),
            "TRANSCRIPTION_FAILED",
            "Audio transcription request failed",
            False,
        ),
    ],
)
def test_maps_failures_without_leaking_details(
    tmp_path: Path,
    error: Exception,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(files=FakeFiles(events), models=FakeModels(events, [error]))
    chunk = make_chunk(tmp_path, "SECRET-chunk.mp3")

    with pytest.raises(DigestError) as raised:
        GeminiAudioTranscriber(client, "test-model").transcribe([chunk])

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    rendered = rendered_exception(raised.value)
    for secret in ("SECRET", "private", "chunk.mp3"):
        assert secret not in str(raised.value)
        assert secret not in rendered
    assert raised.value.__cause__ is None


def test_upload_failure_does_not_attempt_remote_cleanup(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=ControlledFiles(events, upload_error=RuntimeError("SECRET upload")),
        models=FakeModels(events, []),
    )

    with pytest.raises(DigestError):
        GeminiAudioTranscriber(client, "test-model").transcribe([make_chunk(tmp_path, "chunk.mp3")])

    assert events == [("upload", "chunk.mp3")]


def test_generation_failure_attempts_remote_cleanup_once(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=ControlledFiles(events),
        models=FakeModels(events, [RuntimeError("SECRET generation")]),
    )

    with pytest.raises(DigestError):
        GeminiAudioTranscriber(client, "test-model").transcribe([make_chunk(tmp_path, "chunk.mp3")])

    assert [event for event in events if event[0] == "delete"] == [
        ("delete", "files/chunk-1")
    ]


def test_cleanup_failure_after_success_is_safe_and_non_retryable(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(events, delete_error=RuntimeError("SECRET files/private")),
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
    assert len([event for event in events if event[0] == "delete"]) == 1
    assert sleeps == []
    for marker in ("SECRET", "private"):
        assert marker not in str(raised.value)
        assert marker not in rendered_exception(raised.value)


def test_cleanup_nonretryable_client_error_fails_once_without_sleep(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(
            events,
            delete_error=errors.ClientError(400, {"message": "SECRET cleanup-400"}, None),
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
    assert len([event for event in events if event[0] == "delete"]) == 1
    assert sleeps == []
    assert "SECRET cleanup-400" not in rendered_exception(raised.value)


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


def test_primary_failure_wins_when_generation_and_cleanup_both_fail(tmp_path: Path) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=ControlledFiles(events, delete_error=RuntimeError("SECRET cleanup")),
        models=FakeModels(events, [httpx.TimeoutException("SECRET generation")]),
    )

    with pytest.raises(DigestError) as raised:
        GeminiAudioTranscriber(client, "test-model").transcribe([make_chunk(tmp_path, "chunk.mp3")])

    assert (raised.value.code, raised.value.retryable) == ("TRANSCRIPTION_TIMEOUT", True)
    assert len([event for event in events if event[0] == "delete"]) == 1
    assert "SECRET" not in rendered_exception(raised.value)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(2)])
def test_cleanup_interrupt_wins_over_ordinary_primary_failure(
    tmp_path: Path, interrupt: BaseException
) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(events, delete_error=interrupt),
        models=FakeModels(events, [RuntimeError("SECRET generation")]),
    )

    with pytest.raises(type(interrupt)):
        GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
            [make_chunk(tmp_path, "chunk.mp3")]
        )

    assert len([event for event in events if event[0] == "delete"]) == 1
    assert sleeps == []


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(2)])
def test_generation_interrupt_cleans_up_then_propagates(
    tmp_path: Path, interrupt: BaseException
) -> None:
    events: list[tuple[str, str]] = []
    client = SimpleNamespace(
        files=ControlledFiles(events),
        models=FakeModels(events, [interrupt]),
    )

    with pytest.raises(type(interrupt)):
        GeminiAudioTranscriber(client, "test-model").transcribe([make_chunk(tmp_path, "chunk.mp3")])

    assert len([event for event in events if event[0] == "delete"]) == 1
    assert [event for event in events if event[0] == "delete"] == [
        ("delete", "files/chunk-1")
    ]


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


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(2)])
def test_cleanup_interrupt_propagates(tmp_path: Path, interrupt: BaseException) -> None:
    events: list[tuple[str, str]] = []
    sleeps: list[float] = []
    client = SimpleNamespace(
        files=ControlledFiles(events, delete_error=interrupt),
        models=FakeModels(events, [SimpleNamespace(text="complete transcript")]),
    )

    with pytest.raises(type(interrupt)):
        GeminiAudioTranscriber(client, "test-model", sleeper=sleeps.append).transcribe(
            [make_chunk(tmp_path, "chunk.mp3")]
        )

    assert len([event for event in events if event[0] == "delete"]) == 1
    assert sleeps == []
