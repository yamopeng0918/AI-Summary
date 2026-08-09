"""Safe extraction of directly readable public web articles."""

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import ipaddress
import socket
from typing import Callable
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


@dataclass(frozen=True)
class _ConnectionTarget:
    url: str
    address: str
    host: str
    host_header: str


def _validate_destination(url: str) -> _ConnectionTarget:
    """Resolve and validate a public URL once, returning its pinned address."""
    try:
        normalized = normalize_public_url(url)
        parsed = urlsplit(normalized)
        host = parsed.hostname
        if host is None:
            raise ValueError("missing host")
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError("no addresses")
        validated_addresses: list[str] = []
        for address_info in addresses:
            address = ipaddress.ip_address(address_info[4][0])
            if not address.is_global:
                raise ValueError("non-public address")
            validated_addresses.append(address.compressed)
        is_default_port = (parsed.scheme == "http" and parsed.port == 80) or (
            parsed.scheme == "https" and parsed.port == 443
        )
        hostname = f"[{host}]" if ":" in host else host
        host_header = hostname if is_default_port or parsed.port is None else f"{hostname}:{parsed.port}"
        return _ConnectionTarget(normalized, validated_addresses[0], host, host_header)
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
            self.has_login_form = any(marker in action for marker in ("/login", "/signin", "/sign-in"))
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
        target = _validate_destination(url)
        redirects = 0

        while True:
            client: httpx.Client | None = None
            response: httpx.Response | None = None
            try:
                client = self._client_factory()
                request = client.build_request(
                    "GET",
                    httpx.URL(target.url).copy_with(host=target.address),
                    headers={"User-Agent": _USER_AGENT, "Host": target.host_header},
                    timeout=_TIMEOUT_SECONDS,
                )
                request.extensions["sni_hostname"] = target.host
                response = client.send(request, stream=True, follow_redirects=False)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise _error("HTTP_ERROR", "Source returned an invalid redirect", False)
                    if redirects >= _MAX_REDIRECTS:
                        raise _error("TOO_MANY_REDIRECTS", "Source redirected too many times", False)
                    target = _validate_destination(urljoin(target.url, location))
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
                if declared_length:
                    try:
                        declared_size = int(declared_length)
                    except ValueError as error:
                        raise _error("INVALID_CONTENT_LENGTH", "Source sent an invalid content length", False) from error
                    if declared_size < 0:
                        raise _error("INVALID_CONTENT_LENGTH", "Source sent an invalid content length", False)
                    if declared_size > _MAX_RESPONSE_BYTES:
                        raise _error("RESPONSE_TOO_LARGE", "Source response is too large", False)

                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise _error("RESPONSE_TOO_LARGE", "Source response is too large", False)
                html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                text = _extract_main_text(html)
                access_error = _access_wall_error(html, text)
                if access_error is not None:
                    raise access_error
                return self._extract_article(target.url, html, text)
            except httpx.TimeoutException as error:
                raise _error("NETWORK_TIMEOUT", "Source request timed out", True) from error
            except httpx.HTTPError as error:
                raise _error("NETWORK_ERROR", "Source request failed", True) from error
            finally:
                if response is not None:
                    response.close()
                if client is not None:
                    client.close()

    def _extract_article(self, canonical_url: str, html: str, text: str) -> ExtractedArticle:
        metadata = extract_metadata(html)
        fallback_author, fallback_date = _fallback_metadata(html)
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
