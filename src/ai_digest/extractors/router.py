"""Route canonical source URLs to their matching extractors."""

from collections.abc import Callable

from ai_digest.domain import ExtractedArticle
from ai_digest.extractors.base import Extractor
from ai_digest.source_urls import is_bluesky_url, is_youtube_url


class LazyExtractor:
    """Construct a source-specific extractor only when its route is selected."""

    def __init__(self, factory: Callable[[], Extractor]) -> None:
        self._factory = factory

    def extract(self, url: str) -> ExtractedArticle:
        return self._factory().extract(url)


class ExtractorRouter:
    def __init__(self, web: Extractor, youtube: Extractor, bluesky: Extractor) -> None:
        self._web = web
        self._youtube = youtube
        self._bluesky = bluesky

    def extract(self, url: str) -> ExtractedArticle:
        if is_youtube_url(url):
            return self._youtube.extract(url)
        if is_bluesky_url(url):
            return self._bluesky.extract(url)
        return self._web.extract(url)
