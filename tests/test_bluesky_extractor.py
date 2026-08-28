from copy import deepcopy
import json
from pathlib import Path
import traceback

import httpx
import pytest

from ai_digest.domain import DigestError
from ai_digest.extractors.bluesky import BlueskyAppViewClient, BlueskyExtractor


BLUESKY_URL = "https://bsky.app/profile/alice.example/post/3social"
FIXTURE = Path(__file__).parent / "fixtures" / "bluesky" / "post.json"


def fixture_post() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeAppView:
    def resolve_handle(self, handle: str) -> str:
        assert handle == "alice.example"
        return "did:plc:alice"

    def get_post(self, uri: str) -> dict[str, object]:
        assert uri == "at://did:plc:alice/app.bsky.feed.post/3social"
        return fixture_post()


class StaticAppView:
    def __init__(self, post: object, *, did: object = "did:plc:alice") -> None:
        self.post = post
        self.did = did
        self.resolve_calls: list[str] = []
        self.post_calls: list[str] = []

    def resolve_handle(self, handle: str) -> object:
        self.resolve_calls.append(handle)
        return self.did

    def get_post(self, uri: str) -> object:
        self.post_calls.append(uri)
        return deepcopy(self.post)


class FailingAppView:
    def __init__(self, failure: BaseException, *, fail_resolve: bool = True) -> None:
        self.failure = failure
        self.fail_resolve = fail_resolve

    def resolve_handle(self, handle: str) -> str:
        if self.fail_resolve:
            raise self.failure
        return "did:plc:alice"

    def get_post(self, uri: str) -> dict[str, object]:
        raise self.failure


def record(post: dict[str, object]) -> dict[str, object]:
    value = post["record"]
    assert isinstance(value, dict)
    return value


def author(post: dict[str, object]) -> dict[str, object]:
    value = post["author"]
    assert isinstance(value, dict)
    return value


def rendered_exception(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_extracts_only_approved_bluesky_text() -> None:
    article = BlueskyExtractor(FakeAppView()).extract(BLUESKY_URL)

    assert str(article.canonical_url) == (
        "https://bsky.app/profile/did:plc:alice/post/3social"
    )
    assert article.source_type == "social"
    assert article.title == "Alice（@alice.example）的 Bluesky 貼文"
    assert article.author == "Alice"
    assert article.published_at is not None
    assert article.published_at.isoformat() == "2026-08-28T01:02:03+00:00"
    assert article.text == (
        "貼文：\n公開貼文 #AI\n\n"
        "圖片替代文字：\n架構圖\n\n"
        "外部連結標題：\nAI Digest 文件"
    )
    assert "引用貼文不得出現" not in article.text


def test_did_input_does_not_resolve_handle() -> None:
    appview = StaticAppView(fixture_post())

    article = BlueskyExtractor(appview).extract(
        "https://bsky.app/profile/did:plc:alice/post/3social"
    )

    assert appview.resolve_calls == []
    assert appview.post_calls == [
        "at://did:plc:alice/app.bsky.feed.post/3social"
    ]
    assert str(article.canonical_url) == (
        "https://bsky.app/profile/did:plc:alice/post/3social"
    )


def test_uses_handle_when_display_name_is_blank() -> None:
    post = fixture_post()
    author(post)["displayName"] = "   "

    article = BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert article.title == "alice.example（@alice.example）的 Bluesky 貼文"
    assert article.author == "alice.example"


@pytest.mark.parametrize(
    ("text", "embed", "expected"),
    [
        ("只有正文", None, "貼文：\n只有正文"),
        (
            "   ",
            {
                "$type": "app.bsky.embed.images#view",
                "images": [{"alt": "替代文字"}],
            },
            "圖片替代文字：\n替代文字",
        ),
        (
            "",
            {
                "$type": "app.bsky.embed.external#view",
                "external": {"title": "卡片標題"},
            },
            "外部連結標題：\n卡片標題",
        ),
    ],
)
def test_extracts_each_approved_content_kind_independently(
    text: str, embed: object, expected: str
) -> None:
    post = fixture_post()
    record(post)["text"] = text
    if embed is None:
        post.pop("embed", None)
    else:
        post["embed"] = embed

    article = BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert article.text == expected


def test_deduplicates_nonblank_supplemental_text_in_order() -> None:
    post = fixture_post()
    record(post)["text"] = ""
    post["embed"] = {
        "$type": "app.bsky.embed.images#view",
        "images": [
            {"alt": " 第一張 "},
            {"alt": "第一張"},
            {"alt": ""},
            {"alt": "第二張"},
        ],
    }

    article = BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert article.text == "圖片替代文字：\n第一張\n第二張"


def test_record_with_media_uses_only_current_post_media() -> None:
    post = fixture_post()
    record(post)["text"] = ""
    post["embed"] = {
        "$type": "app.bsky.embed.recordWithMedia#view",
        "media": {
            "$type": "app.bsky.embed.images#view",
            "images": [{"alt": "目前貼文圖片"}],
        },
        "record": {
            "$type": "app.bsky.embed.record#view",
            "record": {
                "value": {"text": "引用貼文不得出現"},
                "embeds": [
                    {
                        "$type": "app.bsky.embed.external#view",
                        "external": {"title": "引用連結不得出現"},
                    }
                ],
            },
        },
    }

    article = BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert article.text == "圖片替代文字：\n目前貼文圖片"


def test_rejects_post_without_approved_content() -> None:
    post = fixture_post()
    record(post)["text"] = "   "
    post.pop("embed")

    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "NO_EXTRACTABLE_CONTENT",
        "message": "Bluesky post does not contain extractable text",
        "retryable": False,
    }


def test_rejects_reply_post() -> None:
    post = fixture_post()
    record(post)["reply"] = {
        "root": {"uri": "at://did:plc:root/app.bsky.feed.post/root", "cid": "root"},
        "parent": {
            "uri": "at://did:plc:parent/app.bsky.feed.post/parent",
            "cid": "parent",
        },
    }

    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "REPLY_POST_NOT_SUPPORTED",
        "message": "Bluesky replies are not supported",
        "retryable": False,
    }


def test_rejects_author_did_mismatch() -> None:
    post = fixture_post()
    author(post)["did"] = "did:plc:other"

    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        "INVALID_SOURCE_RESPONSE",
        False,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda post: post.__setitem__("record", "SECRET_RECORD"),
        lambda post: record(post).pop("text"),
        lambda post: record(post).__setitem__("text", ["SECRET_TEXT"]),
        lambda post: post.__setitem__("author", ["SECRET_AUTHOR"]),
        lambda post: author(post).__setitem__("handle", " "),
        lambda post: record(post).__setitem__("reply", "SECRET_REPLY"),
    ],
)
def test_rejects_malformed_post_records_safely(mutate) -> None:
    post = fixture_post()
    mutate(post)

    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "INVALID_SOURCE_RESPONSE",
        "message": "Bluesky returned an invalid response",
        "retryable": False,
    }
    assert "SECRET" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    "created_at",
    ["not-a-timestamp", "2026-08-28T01:02:03", ["SECRET_TIMESTAMP"]],
)
def test_rejects_malformed_or_naive_timestamp(created_at: object) -> None:
    post = fixture_post()
    record(post)["createdAt"] = created_at

    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert (raised.value.code, raised.value.retryable) == (
        "INVALID_SOURCE_RESPONSE",
        False,
    )
    assert "SECRET" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            DigestError(
                "extract",
                "POST_NOT_FOUND",
                "Bluesky post was not found",
                False,
            ),
            ("POST_NOT_FOUND", False),
        ),
        (
            DigestError(
                "extract",
                "SOURCE_ACCESS_DENIED",
                "Bluesky post is not publicly accessible",
                False,
            ),
            ("SOURCE_ACCESS_DENIED", False),
        ),
        (TimeoutError("SECRET_TIMEOUT"), ("UPSTREAM_UNAVAILABLE", True)),
    ],
)
def test_sanitizes_appview_failures(
    failure: Exception, expected: tuple[str, bool]
) -> None:
    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(FailingAppView(failure)).extract(BLUESKY_URL)

    assert (raised.value.code, raised.value.retryable) == expected
    if not isinstance(failure, DigestError):
        assert raised.value.as_dict() == {
            "stage": "extract",
            "code": "UPSTREAM_UNAVAILABLE",
            "message": "Bluesky service is unavailable",
            "retryable": True,
        }
        assert "SECRET_TIMEOUT" not in rendered_exception(raised.value)


def test_sanitizes_unexpected_get_post_exception() -> None:
    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(
            FailingAppView(RuntimeError("SECRET_GET_POST"), fail_resolve=False)
        ).extract(BLUESKY_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "UPSTREAM_UNAVAILABLE",
        "message": "Bluesky service is unavailable",
        "retryable": True,
    }
    assert "SECRET_GET_POST" not in rendered_exception(raised.value)


@pytest.mark.parametrize("post", [None, [], "SECRET_POST"])
def test_rejects_non_object_post_response(post: object) -> None:
    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(post)).extract(BLUESKY_URL)

    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET" not in rendered_exception(raised.value)


@pytest.mark.parametrize("did", [None, "", "plc:alice", ["SECRET_DID"]])
def test_rejects_malformed_resolved_did(did: object) -> None:
    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(StaticAppView(fixture_post(), did=did)).extract(BLUESKY_URL)

    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET" not in rendered_exception(raised.value)


def client_for(
    transport: httpx.BaseTransport,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> callable:
    return lambda: httpx.Client(
        transport=transport,
        headers=headers,
        cookies=cookies,
        follow_redirects=True,
    )


def test_appview_uses_only_fixed_xrpc_requests_without_credentials_or_embeds() -> None:
    requests: list[httpx.Request] = []
    clients: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("resolveHandle"):
            return httpx.Response(200, json={"did": "did:plc:alice"})
        if request.url.path.endswith("getPosts"):
            return httpx.Response(200, json={"posts": [fixture_post()]})
        pytest.fail(f"unexpected request: {request.url}")

    def factory() -> httpx.Client:
        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer SECRET_TOKEN"},
            cookies={"session": "SECRET_COOKIE"},
            follow_redirects=True,
        )
        clients.append(client)
        return client

    article = BlueskyExtractor(BlueskyAppViewClient(factory)).extract(BLUESKY_URL)

    assert article.author == "Alice"
    assert [f"{request.method} {request.url}" for request in requests] == [
        "GET https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=alice.example",
        "GET https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?uris=at%3A%2F%2Fdid%3Aplc%3Aalice%2Fapp.bsky.feed.post%2F3social",
    ]
    for request in requests:
        assert request.headers["accept"] == "application/json"
        assert request.headers["user-agent"] == (
            "AI-Digest/0.1 (+https://github.com/ai-digest)"
        )
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert request.extensions["timeout"] == {
            "connect": 15.0,
            "read": 15.0,
            "write": 15.0,
            "pool": 15.0,
        }
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_appview_does_not_follow_redirects() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/SECRET_REDIRECT"},
        )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(
            client_for(httpx.MockTransport(handler))
        ).resolve_handle("alice.example")

    assert requested_urls == [
        "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=alice.example"
    ]
    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET_REDIRECT" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    ("method", "status_code", "expected"),
    [
        ("resolve_handle", 400, ("AUTHOR_NOT_FOUND", False)),
        ("resolve_handle", 404, ("AUTHOR_NOT_FOUND", False)),
        ("get_post", 400, ("POST_NOT_FOUND", False)),
        ("get_post", 404, ("POST_NOT_FOUND", False)),
        ("resolve_handle", 401, ("SOURCE_ACCESS_DENIED", False)),
        ("get_post", 403, ("SOURCE_ACCESS_DENIED", False)),
        ("resolve_handle", 429, ("UPSTREAM_UNAVAILABLE", True)),
        ("get_post", 500, ("UPSTREAM_UNAVAILABLE", True)),
        ("get_post", 503, ("UPSTREAM_UNAVAILABLE", True)),
    ],
)
def test_appview_maps_http_statuses_to_approved_errors(
    method: str, status_code: int, expected: tuple[str, bool]
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code,
            headers={"content-type": "application/json"},
            text='{"error":"SECRET_BODY"}',
        )
    )
    appview = BlueskyAppViewClient(client_for(transport))

    with pytest.raises(DigestError) as raised:
        if method == "resolve_handle":
            appview.resolve_handle("alice.example")
        else:
            appview.get_post(
                "at://did:plc:alice/app.bsky.feed.post/3social"
            )

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        *expected,
    )
    assert "SECRET_BODY" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("SECRET_TIMEOUT"),
        httpx.ConnectError("SECRET_CONNECT"),
    ],
)
def test_appview_maps_transport_failures_to_retryable_error(
    error: httpx.HTTPError,
) -> None:
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(error)
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).resolve_handle(
            "alice.example"
        )

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "UPSTREAM_UNAVAILABLE",
        "message": "Bluesky service is unavailable",
        "retryable": True,
    }
    assert "SECRET" not in rendered_exception(raised.value)


def test_appview_sanitizes_unexpected_client_failure() -> None:
    def factory() -> httpx.Client:
        raise RuntimeError("SECRET_CLIENT_FAILURE")

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(factory).resolve_handle("alice.example")

    assert (raised.value.code, raised.value.retryable) == (
        "UPSTREAM_UNAVAILABLE",
        True,
    )
    assert "SECRET_CLIENT_FAILURE" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8", "application/atproto+json"],
)
def test_appview_accepts_json_media_types(content_type: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": content_type},
            content=b'{"did":"did:plc:alice"}',
        )
    )

    assert (
        BlueskyAppViewClient(client_for(transport)).resolve_handle("alice.example")
        == "did:plc:alice"
    )


def test_appview_rejects_non_json_content_type_without_exposing_body() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="SECRET_HTML_BODY",
        )
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).resolve_handle(
            "alice.example"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "INVALID_SOURCE_RESPONSE",
        False,
    )
    assert "SECRET_HTML_BODY" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-length": str(2 * 1024 * 1024 + 1),
            },
        ),
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"x" * (2 * 1024 * 1024 + 1),
        ),
    ],
)
def test_appview_rejects_responses_larger_than_two_mib(
    response: httpx.Response,
) -> None:
    transport = httpx.MockTransport(lambda request: response)

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).resolve_handle(
            "alice.example"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "INVALID_SOURCE_RESPONSE",
        False,
    )


@pytest.mark.parametrize("content_length", ["SECRET_LENGTH", "-1"])
def test_appview_rejects_invalid_content_length_safely(
    content_length: str,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-length": content_length,
            },
        )
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).resolve_handle(
            "alice.example"
        )

    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET_LENGTH" not in rendered_exception(raised.value)


def test_appview_rejects_invalid_json_without_exposing_body() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text="SECRET_NOT_JSON",
        )
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).resolve_handle(
            "alice.example"
        )

    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET_NOT_JSON" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"did": ""},
        {"did": "plc:alice"},
        {"did": ["SECRET_DID"]},
    ],
)
def test_resolve_handle_rejects_malformed_payload_safely(payload: object) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).resolve_handle(
            "alice.example"
        )

    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET" not in rendered_exception(raised.value)


def test_get_post_maps_empty_posts_to_not_found() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"posts": []})
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).get_post(
            "at://did:plc:alice/app.bsky.feed.post/3social"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "POST_NOT_FOUND",
        False,
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"posts": "SECRET_POSTS"},
        {"posts": ["SECRET_POST"]},
        {"posts": [{"uri": "at://did:plc:other/app.bsky.feed.post/other"}]},
        {"posts": [fixture_post(), fixture_post()]},
    ],
)
def test_get_post_rejects_malformed_or_nonmatching_payload_safely(
    payload: object,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )

    with pytest.raises(DigestError) as raised:
        BlueskyAppViewClient(client_for(transport)).get_post(
            "at://did:plc:alice/app.bsky.feed.post/3social"
        )

    assert raised.value.code == "INVALID_SOURCE_RESPONSE"
    assert "SECRET" not in rendered_exception(raised.value)
