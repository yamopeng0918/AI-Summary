"""Safe extraction of directly readable public web articles."""

from datetime import datetime
from html.parser import HTMLParser
from typing import Callable

import httpx
from pydantic import ValidationError
import trafilatura
from trafilatura.metadata import extract_metadata

from ai_digest.domain import DigestError, ExtractedArticle
from ai_digest.extractors.public_http import PublicHttpDownloader


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3
_MIN_TEXT_LENGTH = 200
_TIMEOUT_SECONDS = 15.0
_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}


def _error(code: str, message: str, retryable: bool) -> DigestError:
    return DigestError("extract", code, message, retryable)


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _trim_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class _MetadataParser(HTMLParser):
    """Collect common page metadata where extraction metadata is incomplete."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        key = (attributes.get("name") or attributes.get("property") or "").lower()
        value = attributes.get("content")
        if key and value:
            self.values.setdefault(key, value)


def _fallback_metadata(html: str) -> tuple[str | None, datetime | None]:
    parser = _MetadataParser()
    parser.feed(html)
    author = parser.values.get("author") or parser.values.get("article:author")
    date = _published_at(
        parser.values.get("article:published_time")
        or parser.values.get("date")
        or parser.values.get("publishdate")
    )
    return author, date


class _AccessWallParser(HTMLParser):
    """Recognize explicit login and paywall page structures conservatively."""

    def __init__(self) -> None:
        super().__init__()
        self.has_login_form = False
        self.has_password_input = False
        self.has_access_overlay = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "").lower() for key, value in attrs}
        if tag == "form":
            action = attributes.get("action", "")
            self.has_login_form |= any(marker in action for marker in ("/login", "/signin", "/sign-in"))
        if tag == "input" and attributes.get("type") == "password":
            self.has_password_input = True
        tokens = set(attributes.get("class", "").split()) | {attributes.get("id", "")}
        if tokens & {"paywall", "subscription-wall", "login-overlay", "access-denied"}:
            self.has_access_overlay = True
        if tag == "meta":
            name = attributes.get("name") or attributes.get("property")
            content = attributes.get("content", "")
            if name in {"access", "article:access", "content-visibility"} and content in {
                "login-required",
                "subscriber-only",
                "paywall",
            }:
                self.has_access_overlay = True


def _access_wall_error(html: str, text: str) -> DigestError | None:
    parser = _AccessWallParser()
    parser.feed(html)
    if parser.has_password_input and parser.has_login_form:
        return _error("LOGIN_REQUIRED", "Source requires login", False)
    if parser.has_access_overlay:
        return _error("CONTENT_UNAVAILABLE", "Source content is unavailable", False)
    return None


def _extract_main_text(html: str) -> str:
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class WebExtractor:
    """Retrieve one public HTML page and extract its readable article content."""

    def __init__(self, client_factory: Callable[[], httpx.Client]) -> None:
        """Create an isolated HTTPX client for each validated request hop."""
        self._client_factory = client_factory

    def extract(self, url: str) -> ExtractedArticle:
        response = PublicHttpDownloader(
            self._client_factory,
            allowed_content_types=_HTML_CONTENT_TYPES,
            invalid_content_type_message="Source is not an HTML page",
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            max_bytes=_MAX_RESPONSE_BYTES,
            max_redirects=_MAX_REDIRECTS,
            timeout=_TIMEOUT_SECONDS,
        ).get(url)
        html = response.body.decode(response.encoding, errors="replace")
        text = _extract_main_text(html)
        access_error = _access_wall_error(html, text)
        if access_error is not None:
            raise access_error
        return self._extract_article(response.canonical_url, html, text)

    def _extract_article(self, canonical_url: str, html: str, text: str) -> ExtractedArticle:
        metadata = extract_metadata(html)
        fallback_author, fallback_date = _fallback_metadata(html)
        if len(text) < _MIN_TEXT_LENGTH:
            raise _error("INSUFFICIENT_TEXT", "Source does not contain enough article text", False)
        title = _trim_optional(metadata.title)
        if not title:
            raise _error("INSUFFICIENT_TEXT", "Source does not contain an article title", False)
        try:
            return ExtractedArticle(
                canonical_url=canonical_url,
                title=title,
                author=_trim_optional(metadata.author) or _trim_optional(fallback_author),
                published_at=fallback_date or _published_at(metadata.date),
                text=text,
            )
        except ValidationError as error:
            raise _error("INVALID_METADATA", "Source metadata is invalid", False) from error
