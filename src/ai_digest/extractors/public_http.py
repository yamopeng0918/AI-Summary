"""Bounded, SSRF-safe HTTP retrieval for public source extractors."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ai_digest.domain import DigestError
from ai_digest.url_normalizer import normalize_public_url


_USER_AGENT = "AI-Digest/0.1 (+https://github.com/ai-digest)"


def _error(code: str, message: str, retryable: bool) -> DigestError:
    return DigestError("extract", code, message, retryable)


@dataclass(frozen=True)
class _ConnectionTarget:
    url: str
    canonical_url: str
    address: str
    host: str
    host_header: str


@dataclass(frozen=True)
class PublicHttpResponse:
    """Validated response data detached from its closed HTTP connection."""

    canonical_url: str
    content_type: str
    encoding: str
    body: bytes


def _validate_destination(
    url: str, *, preserve_trailing_slash: bool = False
) -> _ConnectionTarget:
    try:
        normalized = normalize_public_url(url)
        parsed = urlsplit(normalized)
        original = urlsplit(url)
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
        host_header = (
            hostname
            if is_default_port or parsed.port is None
            else f"{hostname}:{parsed.port}"
        )
        transport_path = parsed.path
        if (
            preserve_trailing_slash
            and original.path.endswith("/")
            and transport_path != "/"
        ):
            transport_path += "/"
        transport_url = urlunsplit(
            (parsed.scheme, parsed.netloc, transport_path, parsed.query, "")
        )
        return _ConnectionTarget(
            transport_url,
            normalized,
            validated_addresses[0],
            host,
            host_header,
        )
    except (DigestError, OSError, ValueError):
        raise _error(
            "UNSAFE_DESTINATION",
            "URL destination is not publicly reachable",
            False,
        ) from None


class PublicHttpDownloader:
    """Fetch one bounded public resource while pinning every validated hop."""

    def __init__(
        self,
        client_factory: Callable[[], httpx.Client],
        *,
        allowed_content_types: Collection[str],
        invalid_content_type_message: str,
        accept: str,
        max_bytes: int,
        max_redirects: int,
        timeout: float,
    ) -> None:
        self._client_factory = client_factory
        self._allowed_content_types = frozenset(allowed_content_types)
        self._invalid_content_type_message = invalid_content_type_message
        self._accept = accept
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._timeout = timeout

    def get(self, url: str) -> PublicHttpResponse:
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
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Accept": self._accept,
                        "Host": target.host_header,
                    },
                    timeout=self._timeout,
                )
                request.extensions["sni_hostname"] = target.host
                response = client.send(
                    request, stream=True, follow_redirects=False
                )
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise _error(
                            "HTTP_ERROR", "Source returned an invalid redirect", False
                        )
                    if redirects >= self._max_redirects:
                        raise _error(
                            "TOO_MANY_REDIRECTS",
                            "Source redirected too many times",
                            False,
                        )
                    target = _validate_destination(
                        urljoin(target.url, location),
                        preserve_trailing_slash=True,
                    )
                    redirects += 1
                    continue

                if response.status_code >= 400:
                    if response.status_code in {401, 403}:
                        raise _error(
                            "LOGIN_REQUIRED", "Source requires login", False
                        )
                    raise _error(
                        "HTTP_ERROR",
                        "Source returned an HTTP error",
                        response.status_code == 429 or response.status_code >= 500,
                    )

                content_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .lower()
                )
                if content_type not in self._allowed_content_types:
                    raise _error(
                        "INVALID_CONTENT_TYPE",
                        self._invalid_content_type_message,
                        False,
                    )

                declared_length = response.headers.get("content-length")
                if declared_length:
                    try:
                        declared_size = int(declared_length)
                    except ValueError:
                        raise _error(
                            "INVALID_CONTENT_LENGTH",
                            "Source sent an invalid content length",
                            False,
                        ) from None
                    if declared_size < 0:
                        raise _error(
                            "INVALID_CONTENT_LENGTH",
                            "Source sent an invalid content length",
                            False,
                        )
                    if declared_size > self._max_bytes:
                        raise _error(
                            "RESPONSE_TOO_LARGE",
                            "Source response is too large",
                            False,
                        )

                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise _error(
                            "RESPONSE_TOO_LARGE",
                            "Source response is too large",
                            False,
                        )
                return PublicHttpResponse(
                    canonical_url=target.canonical_url,
                    content_type=content_type,
                    encoding=response.encoding or "utf-8",
                    body=bytes(body),
                )
            except httpx.TimeoutException:
                raise _error(
                    "NETWORK_TIMEOUT", "Source request timed out", True
                ) from None
            except httpx.HTTPError:
                raise _error("NETWORK_ERROR", "Source request failed", True) from None
            finally:
                if response is not None:
                    response.close()
                if client is not None:
                    client.close()
