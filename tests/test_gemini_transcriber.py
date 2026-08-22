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


from ai_digest.transcribers import AudioTranscriber


def accepts_transcriber(value: AudioTranscriber) -> AudioTranscriber:
    return value


def test_gemini_transcriber_satisfies_audio_transcriber_contract() -> None:
    client = SimpleNamespace(files=object(), models=object())
    assert accepts_transcriber(GeminiAudioTranscriber(client, "model")) is not None
