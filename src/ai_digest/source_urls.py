"""Recognize and canonicalize supported source URLs."""

import re
from urllib.parse import parse_qs, urlsplit

from ai_digest.domain import DigestError
from ai_digest.url_normalizer import normalize_public_url


_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


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
