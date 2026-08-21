"""Safe OpenAI adapter for audio transcription."""

from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from ai_digest.domain import DigestError


class OpenAIAudioTranscriber:
    """Transcribe local audio chunks through the OpenAI audio API."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def transcribe(self, chunks: list[Path]) -> str:
        """Return the ordered complete transcript, or a safe extract error."""
        completed: list[str] = []
        for chunk in chunks:
            result, failure = self._transcribe_chunk(chunk)
            if failure is not None:
                raise failure
            text = getattr(result, "text", "").strip()
            if not text:
                raise DigestError(
                    "extract",
                    "TRANSCRIPTION_FAILED",
                    "Audio transcription returned no text",
                    False,
                )
            completed.append(text)
        return "\n".join(completed)

    def _transcribe_chunk(self, chunk: Path) -> tuple[Any | None, DigestError | None]:
        try:
            with chunk.open("rb") as audio:
                return self._client.audio.transcriptions.create(model=self._model, file=audio), None
        except APITimeoutError:
            return None, DigestError(
                "extract", "TRANSCRIPTION_TIMEOUT", "Audio transcription timed out", True
            )
        except RateLimitError:
            return None, DigestError(
                "extract",
                "TRANSCRIPTION_RATE_LIMITED",
                "Audio transcription is rate limited",
                True,
            )
        except APIConnectionError:
            return None, DigestError(
                "extract", "TRANSCRIPTION_FAILED", "Audio transcription request failed", True
            )
        except APIStatusError as error:
            return None, DigestError(
                "extract",
                "TRANSCRIPTION_FAILED",
                "Audio transcription request failed",
                error.status_code >= 500,
            )
        except OSError:
            return None, DigestError(
                "extract", "TRANSCRIPTION_FAILED", "Audio transcription request failed", False
            )


def lazy_openai_transcriber(api_key: str | None, model: str) -> OpenAIAudioTranscriber:
    """Build the OpenAI client only when an audio fallback needs it."""
    if not api_key:
        raise DigestError(
            "input",
            "MISSING_API_KEY",
            "OPENAI_API_KEY is required for YouTube audio transcription",
            False,
        )
    return OpenAIAudioTranscriber(OpenAI(api_key=api_key), model)
