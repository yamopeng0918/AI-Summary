"""Protocol boundary for text classification."""

from typing import Protocol


class Classifier(Protocol):
    """Predict a configured category from plain text."""

    def predict(self, text: str) -> str:
        """Return one category without changing the source text."""
