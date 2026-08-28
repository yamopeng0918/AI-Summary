import pytest

from ai_digest.domain import DigestError
from ai_digest.source_urls import (
    BlueskyPostRef,
    canonicalize_source_url,
    is_bluesky_url,
    is_youtube_url,
    parse_bluesky_post_url,
)


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
    with pytest.raises(DigestError) as raised:
        canonicalize_source_url(raw_url)

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "UNSUPPORTED_YOUTUBE_URL",
        "message": "URL must identify one supported YouTube video",
        "retryable": False,
    }


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "https://bsky.app/profile/alice.example/post/3social?ref=share#thread",
            "https://bsky.app/profile/alice.example/post/3social",
        ),
        (
            "https://bsky.app/profile/did:plc:alice/post/3social",
            "https://bsky.app/profile/did:plc:alice/post/3social",
        ),
    ],
)
def test_canonicalizes_supported_bluesky_post_urls(raw_url: str, expected: str) -> None:
    assert is_bluesky_url(raw_url) is True
    assert canonicalize_source_url(raw_url) == expected


def test_parses_bluesky_post_reference() -> None:
    assert parse_bluesky_post_url("https://bsky.app/profile/alice.example/post/3social") == BlueskyPostRef(
        actor="alice.example",
        post_id="3social",
    )


@pytest.mark.parametrize(
    "raw_url",
    [
        "http://bsky.app/profile/alice.example/post/3social",
        "https://bsky.app/profile/alice.example",
        "https://bsky.app/profile/alice.example/post",
        "https://bsky.app/profile/alice.example/post/3social/extra",
        "https://bsky.app/profile//post/3social",
        "https://bsky.app/profile/alice.example/post/",
        "https://bsky.app.evil.example/profile/alice.example/post/3social",
        "https://user@bsky.app/profile/alice.example/post/3social",
        "https://bsky.app:444/profile/alice.example/post/3social",
        "not-a-url",
    ],
)
def test_rejects_nonapproved_bluesky_urls(raw_url: str) -> None:
    with pytest.raises(DigestError) as raised:
        canonicalize_source_url(raw_url)
    assert raised.value.code == "INVALID_URL"


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://bsky.app/profile/alice.example",
        "https://bsky.app/profile/alice.example/post",
        "https://bsky.app/profile/alice.example/post/3social/extra",
        "http://bsky.app/profile/alice.example/post/3social",
        "https://user@bsky.app/profile/alice.example/post/3social",
        "https://bsky.app:444/profile/alice.example/post/3social",
    ],
)
def test_is_bluesky_url_returns_false_for_invalid_bluesky_posts(raw_url: str) -> None:
    assert is_bluesky_url(raw_url) is False
