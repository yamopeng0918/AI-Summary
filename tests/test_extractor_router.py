from ai_digest.extractors import router as router_module
from ai_digest.extractors.router import ExtractorRouter


class RecordingExtractor:
    def __init__(self, article: object) -> None:
        self.article = article
        self.urls: list[str] = []

    def extract(self, url: str) -> object:
        self.urls.append(url)
        return self.article


def test_routes_canonical_youtube_url_only_to_youtube_extractor() -> None:
    web = RecordingExtractor(None)
    youtube = RecordingExtractor("youtube-result")
    router = ExtractorRouter(web=web, youtube=youtube)

    assert router.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube-result"
    assert web.urls == []
    assert youtube.urls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_routes_ordinary_web_url_only_to_web_extractor() -> None:
    web = RecordingExtractor("web-result")
    youtube = RecordingExtractor(None)

    assert ExtractorRouter(web, youtube).extract("https://example.com/article") == "web-result"
    assert web.urls == ["https://example.com/article"]
    assert youtube.urls == []


def test_lazy_extractor_defers_factory_until_selected() -> None:
    calls: list[str] = []
    lazy = router_module.LazyExtractor(
        lambda: calls.append("factory") or RecordingExtractor("result")
    )

    assert calls == []
    assert lazy.extract("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "result"
    assert calls == ["factory"]
