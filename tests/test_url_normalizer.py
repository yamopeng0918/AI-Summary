import pytest

from ai_digest.domain import DigestError
from ai_digest.url_normalizer import normalize_public_url


def test_normalizes_public_http_url() -> None:
    assert normalize_public_url(
        "HTTPS://Example.COM:443/path/?utm_source=x&b=2&a=1#part"
    ) == "https://example.com/path?a=1&b=2"


def test_removes_default_http_port_and_tracking_parameters() -> None:
    assert normalize_public_url(
        "http://example.com:80/?gclid=abc&fbclid=def&utm_medium=email&keep=value"
    ) == "http://example.com/?keep=value"


@pytest.mark.parametrize(
    ("raw_url", "expected_url"),
    [
        ("https://example.com/a/../article", "https://example.com/article"),
        ("https://example.com/a/./article", "https://example.com/a/article"),
    ],
)
def test_resolves_dot_segments_in_paths(raw_url: str, expected_url: str) -> None:
    assert normalize_public_url(raw_url) == expected_url


@pytest.mark.parametrize(
    "raw_url",
    [
        "ftp://example.com/article",
        "https://user:password@example.com/article",
        "https://localhost/article",
        "https://127.0.0.1/article",
        "https://10.0.0.1/article",
        "https://169.254.1.1/article",
        "https://224.0.0.1/article",
        "https://0.0.0.0/article",
        "https://[::1]/article",
        "https://127.1/article",
        "https://0x7f000001/article",
    ],
)
def test_rejects_non_public_or_unsafe_urls(raw_url: str) -> None:
    with pytest.raises(DigestError) as raised:
        normalize_public_url(raw_url)

    error = raised.value
    assert (error.stage, error.code, error.retryable) == ("input", "INVALID_URL", False)
