"""A development-only classifier with a configured fixed category."""

from ai_digest.domain import DigestError, VALID_CATEGORIES


class FixedClassifier:
    """Return a configured valid category for development workflows only."""

    def __init__(self, category: str) -> None:
        if category not in VALID_CATEGORIES:
            raise DigestError("classify", "INVALID_CATEGORY", "Category is not configured", False)
        self._category = category

    def predict(self, text: str) -> str:
        """Return the configured category without inspecting the text."""
        return self._category

