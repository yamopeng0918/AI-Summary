"""Shared contract for source-specific content extractors."""

from typing import Protocol

from ai_digest.domain import ExtractedArticle


class Extractor(Protocol):
    def extract(self, url: str) -> ExtractedArticle: ...
