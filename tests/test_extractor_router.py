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
