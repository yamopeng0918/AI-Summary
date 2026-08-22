"""Safe Gemini adapter for audio transcription."""

from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.genai import errors

from ai_digest.domain import DigestError


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
            completed.append(self._transcribe_chunk(chunk))
        return "\n".join(completed)

    def _transcribe_chunk(self, chunk: Path) -> str:
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
