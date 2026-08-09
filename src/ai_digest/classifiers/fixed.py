"""Development-only fixed category classifier."""

from ai_digest.domain import DigestError, VALID_CATEGORIES


class FixedClassifier:
    """Development-only adapter that always returns one valid category."""

    def __init__(self, category: str) -> None:
        if category not in VALID_CATEGORIES:
            raise DigestError("classify", "INVALID_CATEGORY", "Predicted category is invalid", False)
        self._category = category

    def predict(self, text: str) -> str:
        """Return the configured category; text is intentionally not modified."""
        return self._category
