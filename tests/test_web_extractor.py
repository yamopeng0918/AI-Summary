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


def client_for(transport: httpx.BaseTransport) -> callable:
    return lambda: httpx.Client(transport=transport)


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


def test_pins_connection_to_validated_ip_while_preserving_host_and_tls_name() -> None:
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["connect_host"] = request.url.host
        observed["host"] = request.headers["host"]
        observed["sni"] = request.extensions["sni_hostname"]
        return httpx.Response(200, headers={"content-type": "text/html"}, text=FIXTURE)

    WebExtractor(client_for(httpx.MockTransport(handler))).extract("https://example.com/article")

    assert observed == {
        "connect_host": "93.184.216.34",
        "host": "example.com",
        "sni": "example.com",
    }


def test_rejects_hostname_that_resolves_to_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 0))],
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(httpx.MockTransport(lambda request: pytest.fail("must not connect")))).extract(
            "https://example.com/article"
        )

    assert raised.value.code == "UNSAFE_DESTINATION"


def test_sets_project_user_agent_and_fifteen_second_timeout() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["user_agent"] = request.headers["user-agent"]
        observed["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, headers={"content-type": "text/html"}, text=FIXTURE)

    WebExtractor(client_for(httpx.MockTransport(handler))).extract("https://example.com/article")

    assert observed["user_agent"] == "AI-Digest/0.1 (+https://github.com/ai-digest)"
    assert observed["timeout"] == {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0}


def test_maps_timeout_to_retryable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(httpx.MockTransport(handler))).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("NETWORK_TIMEOUT", True)


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("offline")])
def test_closes_per_hop_client_when_send_fails(error: httpx.HTTPError) -> None:
    clients: list[httpx.Client] = []

    def factory() -> httpx.Client:
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(error))
        )
        clients.append(client)
        return client

    with pytest.raises(DigestError):
        WebExtractor(factory).extract("https://example.com/article")

    assert len(clients) == 1
    assert clients[0].is_closed


def test_rejects_declared_response_larger_than_two_mib() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": str(2 * 1024 * 1024 + 1)},
        )
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert raised.value.code == "RESPONSE_TOO_LARGE"


def test_rejects_streamed_response_larger_than_two_mib() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * (2 * 1024 * 1024 + 1),
        )
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert raised.value.code == "RESPONSE_TOO_LARGE"


def test_rejects_malformed_content_length() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html", "content-length": "not-a-number"}, text=FIXTURE
        )
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("INVALID_CONTENT_LENGTH", False)


def test_rejects_negative_content_length() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html", "content-length": "-1"}, text=FIXTURE
        )
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("INVALID_CONTENT_LENGTH", False)


def test_rejects_more_than_three_redirects() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": f"/hop-{requests}"})

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(httpx.MockTransport(handler))).extract("https://example.com/article")

    assert (raised.value.code, requests) == ("TOO_MANY_REDIRECTS", 4)


@pytest.mark.parametrize("status_code", [401, 403])
def test_maps_auth_http_failures_to_login_required(status_code: int) -> None:
    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(httpx.MockTransport(lambda request: httpx.Response(status_code)))).extract(
            "https://example.com/article"
        )

    assert (raised.value.code, raised.value.retryable) == ("LOGIN_REQUIRED", False)


def test_rejects_200_login_or_paywall_page() -> None:
    login_page = """<html><title>會員專屬內容</title><body>
    <form action="/login"><input type="email"><input type="password"></form>
    <section class="paywall">請登入後閱讀完整內容</section></body></html>"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=login_page)
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("LOGIN_REQUIRED", False)


def test_rejects_200_paywall_page_without_login_form() -> None:
    paywall_page = "<html><body><div class=\"paywall\">Subscription required</div></body></html>"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=paywall_page)
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("CONTENT_UNAVAILABLE", False)


def test_rejects_long_restricted_teaser_with_login_structure() -> None:
    restricted_page = FIXTURE.replace(
        "</body>",
        "<form action=\"/login\"><input type=\"password\"></form></body>",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=restricted_page)
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("LOGIN_REQUIRED", False)


def test_retains_login_signal_after_a_later_benign_form() -> None:
    restricted_page = FIXTURE.replace(
        "</body>",
        "<form action=\"/login\"><input type=\"password\"></form>"
        "<form action=\"/newsletter\"><input type=\"email\"></form></body>",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=restricted_page)
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("LOGIN_REQUIRED", False)


def test_rejects_long_content_with_explicit_paywall_metadata() -> None:
    restricted_page = FIXTURE.replace(
        "</head>",
        "<meta name=\"access\" content=\"subscriber-only\"></head>",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=restricted_page)
    )

    with pytest.raises(DigestError) as raised:
        WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert (raised.value.code, raised.value.retryable) == ("CONTENT_UNAVAILABLE", False)


def test_isolates_same_ip_cross_host_redirects_into_separate_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    clients: list[httpx.Client] = []
    used_clients: list[int] = []

    def factory() -> httpx.Client:
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (
                    used_clients.append(id(client)),
                    httpx.Response(302, headers={"location": "https://second.example/article"})
                    if request.headers["host"] == "first.example"
                    else httpx.Response(200, headers={"content-type": "text/html"}, text=FIXTURE)
                )[1]
            )
        )
        clients.append(client)
        return client

    WebExtractor(factory).extract("https://first.example/article")

    assert len(clients) == 2
    assert used_clients == [id(client) for client in clients]
    assert all(client.is_closed for client in clients)


def test_accepts_readable_article_that_discusses_paywalls_and_has_teaser_class() -> None:
    readable_page = FIXTURE.replace(
        "</article>",
        "<p>本文討論 paywall 設計與訂閱模式，並比較不同媒體的公開內容策略。</p></article>"
        "<aside class=\"paywall-teaser\">延伸閱讀</aside>",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=readable_page)
    )

    article = WebExtractor(client_for(transport)).extract("https://example.com/article")

    assert "paywall" in article.text
