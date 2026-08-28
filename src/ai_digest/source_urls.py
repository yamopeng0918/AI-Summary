"""Recognize and canonicalize supported source URLs."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from ai_digest.domain import DigestError
from ai_digest.url_normalizer import normalize_public_url


_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_BLUESKY_HOST = "bsky.app"
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class BlueskyPostRef:
    actor: str
    post_id: str


def _invalid_bluesky_url() -> DigestError:
    return DigestError(
        "input", "INVALID_URL", "URL must identify one supported Bluesky post", False
    )


def parse_bluesky_post_url(url: str) -> BlueskyPostRef:
    parsed = urlsplit(normalize_public_url(url))
    parts = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != _BLUESKY_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or len(parts) != 5
        or parts[1] != "profile"
        or parts[3] != "post"
        or not parts[2]
        or not parts[4]
    ):
        raise _invalid_bluesky_url()
    return BlueskyPostRef(actor=parts[2], post_id=parts[4])


def is_bluesky_url(url: str) -> bool:
    try:
        parse_bluesky_post_url(url)
    except DigestError:
        return False
    return True


def is_youtube_url(url: str) -> bool:
    try:
        return (urlsplit(normalize_public_url(url)).hostname or "") in _YOUTUBE_HOSTS
    except DigestError:
        return False


def _unsupported() -> DigestError:
    return DigestError(
        "input", "UNSUPPORTED_YOUTUBE_URL", "URL must identify one supported YouTube video", False
    )


def canonicalize_source_url(raw_url: str) -> str:
    normalized = normalize_public_url(raw_url)
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    if host == _BLUESKY_HOST:
        reference = parse_bluesky_post_url(normalized)
        return f"https://bsky.app/profile/{reference.actor}/post/{reference.post_id}"
    if host.startswith(f"{_BLUESKY_HOST}."):
        raise _invalid_bluesky_url()
    if host not in _YOUTUBE_HOSTS:
        return normalized

    if host == "youtu.be":
        candidate = parsed.path.removeprefix("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith(("/shorts/", "/embed/")):
        candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    else:
        raise _unsupported()
    if not _VIDEO_ID.fullmatch(candidate):
        raise _unsupported()
    return f"https://www.youtube.com/watch?v={candidate}"
