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
        address = _legacy_ipv4_address(host)
    if address is None:
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


def _legacy_ipv4_address(host: str) -> ipaddress.IPv4Address | None:
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    numbers = [_legacy_ipv4_component(part) for part in parts]
    if any(number is None for number in numbers):
        return None

    values = [number for number in numbers if number is not None]
    limits = ((0xFFFFFFFF,), (0xFF, 0xFFFFFF), (0xFF, 0xFF, 0xFFFF), (0xFF,) * 4)
    if any(value > limit for value, limit in zip(values, limits[len(values) - 1])):
        return None

    address = values[-1]
    for index, value in enumerate(values[:-1]):
        address |= value << (24 - index * 8)
    try:
        return ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        return None


def _legacy_ipv4_component(value: str) -> int | None:
    if value.lower().startswith("0x"):
        digits, base = value[2:], 16
    elif len(value) > 1 and value.startswith("0"):
        digits, base = value[1:], 8
    else:
        digits, base = value, 10
    if not digits:
        return None
    try:
        return int(digits, base)
    except ValueError:
        return None


def _remove_dot_segments(path: str) -> str:
    input_buffer = path
    output = ""
    while input_buffer:
        if input_buffer.startswith("../"):
            input_buffer = input_buffer[3:]
        elif input_buffer.startswith("./"):
            input_buffer = input_buffer[2:]
        elif input_buffer.startswith("/./"):
            input_buffer = input_buffer[2:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = input_buffer[3:]
            output = output.rsplit("/", 1)[0]
        elif input_buffer == "/..":
            input_buffer = "/"
            output = output.rsplit("/", 1)[0]
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            separator = input_buffer.find("/", 1) if input_buffer.startswith("/") else input_buffer.find("/")
            if separator == -1:
                output += input_buffer
                input_buffer = ""
            else:
                output += input_buffer[:separator]
                input_buffer = input_buffer[separator:]
    return output


def _normalize_path(path: str) -> str:
    normalized = quote(_remove_dot_segments(unquote(path or "/")), safe=_PATH_SAFE)
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
