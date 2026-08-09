from pathlib import Path
import socket

import httpx
import pytest

from ai_digest.domain import DigestError
from ai_digest.extractors.web import WebExtractor


FIXTURE = (Path(__file__).parent / "fixtures" / "article.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


def client_for(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_extracts_article_metadata_and_main_text_only() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=FIXTURE
        )
    )

    article = WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert str(article.canonical_url) == "https://example.com/article"
    assert article.title == "人工智慧如何改善公共服務"
    assert article.author == "王小明"
    assert article.published_at.isoformat() == "2026-08-09T10:30:00+08:00"
    assert "地方政府近年開始" in article.text
    assert "限時優惠廣告" not in article.text
    assert "首頁｜科技" not in article.text


def test_rejects_redirect_to_private_destination() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        "UNSAFE_DESTINATION",
        False,
    )


def test_rejects_non_html_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/file")

    assert (raised.value.code, raised.value.retryable) == ("INVALID_CONTENT_TYPE", False)


@pytest.mark.parametrize("status_code,retryable", [(404, False), (429, True), (503, True)])
def test_maps_http_failures(status_code: int, retryable: bool) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        "HTTP_ERROR",
        retryable,
    )


def test_rejects_insufficient_extracted_text() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, text="<title>短文</title><article><p>內容太短。</p></article>"
        )
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/short")

    assert (raised.value.code, raised.value.retryable) == ("INSUFFICIENT_TEXT", False)
