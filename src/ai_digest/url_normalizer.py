"""Safety checks and canonicalization for public source URLs."""

import ipaddress
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from ai_digest.domain import DigestError


_TRACKING_PARAMETERS = frozenset({"fbclid", "gclid"})
_PATH_SAFE = "/:@-._~!$&'()*+,;="


def _invalid_url() -> DigestError:
    return DigestError("input", "INVALID_URL", "URL must be a public HTTP(S) URL", False)


def _normalize_host(host: str) -> str:
    host = host.rstrip(".").lower()
    if not host or host == "localhost":
        raise _invalid_url()

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            return host.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise _invalid_url() from error

    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise _invalid_url()
    return address.compressed


def _normalize_path(path: str) -> str:
    normalized = quote(unquote(path or "/"), safe=_PATH_SAFE)
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized or "/"


def normalize_public_url(raw_url: str) -> str:
    """Return the canonical public form of a supplied HTTP(S) URL."""
    try:
        parsed = urlsplit(raw_url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise _invalid_url()
        if parsed.username is not None or parsed.password is not None:
            raise _invalid_url()
        host = _normalize_host(parsed.hostname or "")
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise _invalid_url() from error

    scheme = parsed.scheme.lower()
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    netloc = f"[{host}]" if ":" in host else host
    if include_port:
        netloc = f"{netloc}:{port}"

    retained_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMETERS
    ]
    query = urlencode(sorted(retained_pairs), doseq=True)
    return urlunsplit((scheme, netloc, _normalize_path(parsed.path), query, ""))
