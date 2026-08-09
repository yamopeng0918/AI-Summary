"""Interfaces for article category prediction."""

from typing import Protocol


class Classifier(Protocol):
    """Predict one configured category from plain text."""

    def predict(self, text: str) -> str:
        """Return one category label."""

