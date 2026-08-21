"""Contracts for converting downloaded audio into text."""

from pathlib import Path
from typing import Protocol


class AudioTranscriber(Protocol):
    """Convert ordered audio chunks into one complete transcript."""

    def transcribe(self, chunks: list[Path]) -> str:
        """Return a transcript only after every chunk succeeds."""
