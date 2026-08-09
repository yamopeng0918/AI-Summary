"""Safe extraction of directly readable public web articles."""

from datetime import datetime
from html.parser import HTMLParser
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from trafilatura.metadata import extract_metadata

from ai_digest.domain import DigestError, ExtractedArticle
from ai_digest.url_normalizer import normalize_public_url


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3
_MIN_TEXT_LENGTH = 200
_TIMEOUT_SECONDS = 15.0
_USER_AGENT = "AI-Digest/0.1 (+https://github.com/ai-digest)"
_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}


def _error(code: str, message: str, retryable: bool) -> DigestError:
    return DigestError("extract", code, message, retryable)


def _validate_destination(url: str) -> str:
    """Normalize a URL and ensure every resolved address is public."""
    try:
        normalized = normalize_public_url(url)
        host = urlsplit(normalized).hostname
        if host is None:
            raise ValueError("missing host")
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError("no addresses")
        for address_info in addresses:
            address = ipaddress.ip_address(address_info[4][0])
            if not address.is_global:
                raise ValueError("non-public address")
        return normalized
    except (DigestError, OSError, ValueError) as error:
        raise _error("UNSAFE_DESTINATION", "URL destination is not publicly reachable", False) from error


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


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


class WebExtractor:
    """Retrieve one public HTML page and extract its readable article content."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def extract(self, url: str) -> ExtractedArticle:
        current_url = _validate_destination(url)
        redirects = 0

        while True:
            try:
                request = self._client.build_request(
                    "GET",
                    current_url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_TIMEOUT_SECONDS,
                )
                response = self._client.send(request, stream=True, follow_redirects=False)
            except httpx.TimeoutException as error:
                raise _error("NETWORK_TIMEOUT", "Source request timed out", True) from error
            except httpx.HTTPError as error:
                raise _error("NETWORK_ERROR", "Source request failed", True) from error

            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise _error("HTTP_ERROR", "Source returned an invalid redirect", False)
                    if redirects >= _MAX_REDIRECTS:
                        raise _error("TOO_MANY_REDIRECTS", "Source redirected too many times", False)
                    current_url = _validate_destination(urljoin(current_url, location))
                    redirects += 1
                    continue

                if response.status_code >= 400:
                    if response.status_code in {401, 403}:
                        raise _error("LOGIN_REQUIRED", "Source requires login", False)
                    raise _error(
                        "HTTP_ERROR",
                        "Source returned an HTTP error",
                        response.status_code == 429 or response.status_code >= 500,
                    )

                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in _HTML_CONTENT_TYPES:
                    raise _error("INVALID_CONTENT_TYPE", "Source is not an HTML page", False)

                declared_length = response.headers.get("content-length")
                if declared_length and int(declared_length) > _MAX_RESPONSE_BYTES:
                    raise _error("RESPONSE_TOO_LARGE", "Source response is too large", False)

                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise _error("RESPONSE_TOO_LARGE", "Source response is too large", False)
                return self._extract_article(current_url, bytes(body).decode(response.encoding or "utf-8", errors="replace"))
            finally:
                response.close()

    def _extract_article(self, canonical_url: str, html: str) -> ExtractedArticle:
        metadata = extract_metadata(html)
        fallback_author, fallback_date = _fallback_metadata(html)
        text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(text) < _MIN_TEXT_LENGTH:
            raise _error("INSUFFICIENT_TEXT", "Source does not contain enough article text", False)
        title = metadata.title or ""
        if not title:
            raise _error("INSUFFICIENT_TEXT", "Source does not contain an article title", False)
        return ExtractedArticle(
            canonical_url=canonical_url,
            title=title,
            author=metadata.author or fallback_author,
            published_at=fallback_date or _published_at(metadata.date),
            text=text,
        )
