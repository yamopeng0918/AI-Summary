import pytest

from ai_digest.source_urls import canonicalize_source_url, is_youtube_url


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12&utm_source=test",
        "https://youtu.be/dQw4w9WgXcQ?t=12",
        "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
    ],
)
def test_canonicalizes_supported_youtube_video_forms(raw_url: str) -> None:
    assert is_youtube_url(raw_url) is True
    assert canonicalize_source_url(raw_url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_preserves_existing_web_normalization() -> None:
    assert canonicalize_source_url("HTTPS://EXAMPLE.COM/a?utm_source=x&b=2") == "https://example.com/a?b=2"


@pytest.mark.parametrize("raw_url", ["https://example.com/article", "not-a-url"])
def test_is_youtube_url_returns_false_for_other_or_invalid_urls(raw_url: str) -> None:
    assert is_youtube_url(raw_url) is False


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://www.youtube.com/@OpenAI",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://youtu.be/not valid",
        "https://www.youtube.com/watch?v=short",
    ],
)
def test_rejects_youtube_urls_that_are_not_valid_single_videos(raw_url: str) -> None:
    from ai_digest.domain import DigestError

    with pytest.raises(DigestError) as raised:
        canonicalize_source_url(raw_url)

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "UNSUPPORTED_YOUTUBE_URL",
        "message": "URL must identify one supported YouTube video",
        "retryable": False,
    }
