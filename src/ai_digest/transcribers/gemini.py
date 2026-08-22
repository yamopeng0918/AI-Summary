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
