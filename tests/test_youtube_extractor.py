from contextlib import contextmanager
import socket
import subprocess
import traceback

import httpx
import pytest

from ai_digest.domain import DigestError
from ai_digest.extractors.youtube import (
    YouTubeCaptionClient,
    YouTubeExtractor,
    YtDlpMetadataProbe,
)


VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )


def client_for(transport: httpx.BaseTransport):
    return lambda: httpx.Client(transport=transport)


def public_metadata(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "dQw4w9WgXcQ",
        "title": "公開影片",
        "channel": "公開頻道",
        "upload_date": "20260820",
        "duration": 120,
        "live_status": "not_live",
        "availability": "public",
        "language": "zh-TW",
        "subtitles": {
            "zh-TW": [
                {"url": "https://captions.example/manual.vtt", "ext": "vtt"}
            ]
        },
        "automatic_captions": {},
    }
    value.update(changes)
    return value


def rendered_exception(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_uses_caption_without_media_or_transcriber() -> None:
    extractor = YouTubeExtractor(
        probe=lambda url: public_metadata(),
        caption_client=lambda url: (
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + "字幕內容" * 80
        ),
        media=lambda *args: (_ for _ in ()).throw(
            AssertionError("media must not run")
        ),
        transcriber_factory=lambda: (_ for _ in ()).throw(
            AssertionError("OpenAI must not run")
        ),
        max_duration_seconds=7200,
        chunk_seconds=600,
    )

    article = extractor.extract(VIDEO_URL)

    assert article.source_type == "youtube"
    assert str(article.canonical_url) == VIDEO_URL
    assert article.title == "公開影片"
    assert article.author == "公開頻道"
    assert article.published_at is not None
    assert article.published_at.isoformat() == "2026-08-20T00:00:00+00:00"
    assert "字幕內容" in article.text


def test_no_caption_builds_transcriber_before_downloading_audio(tmp_path) -> None:
    events: list[str] = []
    chunks = [tmp_path / "chunk-0000.mp3", tmp_path / "chunk-0001.mp3"]

    @contextmanager
    def media(url: str, chunk_seconds: int):
        assert url == VIDEO_URL
        assert chunk_seconds == 600
        events.append("media-enter")
        try:
            yield chunks
        finally:
            events.append("media-exit")

    class Transcriber:
        def transcribe(self, supplied):
            events.append("transcribe")
            assert supplied == chunks
            return "完整逐字稿" * 80

    def factory():
        events.append("transcriber-factory")
        return Transcriber()

    extractor = YouTubeExtractor(
        lambda url: events.append("probe")
        or public_metadata(subtitles={}, automatic_captions={}),
        lambda url: pytest.fail("caption client must not run"),
        media,
        factory,
        7200,
        600,
    )

    article = extractor.extract(VIDEO_URL)

    assert events == [
        "probe",
        "transcriber-factory",
        "media-enter",
        "transcribe",
        "media-exit",
    ]
    assert "完整逐字稿" in article.text


def test_missing_transcription_configuration_stops_before_media_download() -> None:
    events: list[str] = []
    missing_key = DigestError(
        "input",
        "MISSING_API_KEY",
        "OPENAI_API_KEY is required for YouTube audio transcription",
        False,
    )
    extractor = YouTubeExtractor(
        lambda url: public_metadata(subtitles={}, automatic_captions={}),
        lambda url: pytest.fail("caption client must not run"),
        lambda *args: events.append("media") or pytest.fail("media must not run"),
        lambda: (_ for _ in ()).throw(missing_key),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert raised.value is missing_key
    assert events == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"availability": "private"}, "CONTENT_UNAVAILABLE"),
        ({"availability": "premium_only"}, "CONTENT_UNAVAILABLE"),
        ({"availability": "subscriber_only"}, "CONTENT_UNAVAILABLE"),
        ({"availability": "unavailable"}, "CONTENT_UNAVAILABLE"),
        ({"availability": "needs_auth"}, "LOGIN_REQUIRED"),
        ({"availability": "needs_subscription"}, "LOGIN_REQUIRED"),
        ({"live_status": "is_live"}, "LIVE_STREAM_UNSUPPORTED"),
        ({"live_status": "is_upcoming"}, "LIVE_STREAM_UNSUPPORTED"),
        ({"duration": 7201}, "VIDEO_TOO_LONG"),
    ],
)
def test_rejects_restricted_live_and_long_videos_before_content_access(
    changes: dict[str, object], code: str
) -> None:
    def forbidden(*args: object):
        pytest.fail("content stage must not run")

    extractor = YouTubeExtractor(
        lambda url: public_metadata(**changes), forbidden, forbidden, forbidden, 7200, 600
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        code,
        False,
    )
    assert "dQw4w9WgXcQ" not in raised.value.message
    assert "公開影片" not in raised.value.message


def test_preserves_safe_probe_access_restriction_error_unchanged() -> None:
    restriction = DigestError(
        "extract", "LOGIN_REQUIRED", "Public media requires authentication", False
    )
    extractor = YouTubeExtractor(
        lambda url: (_ for _ in ()).throw(restriction),
        lambda *args: pytest.fail("content stage must not run"),
        lambda *args: pytest.fail("content stage must not run"),
        lambda *args: pytest.fail("content stage must not run"),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert raised.value is restriction


def test_sanitizes_unexpected_probe_failure() -> None:
    extractor = YouTubeExtractor(
        lambda url: (_ for _ in ()).throw(RuntimeError("SECRET_PROBE_DETAIL")),
        lambda *args: pytest.fail("content stage must not run"),
        lambda *args: pytest.fail("content stage must not run"),
        lambda *args: pytest.fail("content stage must not run"),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "MEDIA_DOWNLOAD_FAILED",
        "message": "YouTube metadata request failed",
        "retryable": True,
    }
    assert "SECRET_PROBE_DETAIL" not in rendered_exception(raised.value)


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        public_metadata(duration="SECRET_DURATION"),
        public_metadata(duration=-1),
        public_metadata(title=""),
        public_metadata(title={"SECRET_TITLE": True}),
    ],
)
def test_sanitizes_invalid_metadata(metadata: object) -> None:
    extractor = YouTubeExtractor(
        lambda url: metadata,
        lambda url: "WEBVTT\n" + "字幕內容" * 80,
        lambda *args: pytest.fail("media must not run"),
        lambda: pytest.fail("OpenAI must not run"),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "INVALID_METADATA",
        "message": "YouTube metadata is invalid",
        "retryable": False,
    }
    assert "SECRET" not in rendered_exception(raised.value)


def test_sanitizes_malformed_caption_payload() -> None:
    extractor = YouTubeExtractor(
        lambda url: public_metadata(),
        lambda url: {"SECRET_CAPTION": True},
        lambda *args: pytest.fail("media must not run"),
        lambda: pytest.fail("OpenAI must not run"),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "INVALID_METADATA",
        "message": "YouTube caption data is invalid",
        "retryable": False,
    }
    assert "SECRET_CAPTION" not in rendered_exception(raised.value)


def test_sanitizes_unexpected_caption_download_failure() -> None:
    extractor = YouTubeExtractor(
        lambda url: public_metadata(),
        lambda url: (_ for _ in ()).throw(RuntimeError("SECRET_CAPTION_FAILURE")),
        lambda *args: pytest.fail("media must not run"),
        lambda: pytest.fail("OpenAI must not run"),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "NETWORK_ERROR",
        "message": "YouTube caption request failed",
        "retryable": True,
    }
    assert "SECRET_CAPTION_FAILURE" not in rendered_exception(raised.value)


def test_rejects_insufficient_caption_text_without_audio_fallback() -> None:
    extractor = YouTubeExtractor(
        lambda url: public_metadata(),
        lambda url: "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n太短",
        lambda *args: pytest.fail("media must not run"),
        lambda: pytest.fail("OpenAI must not run"),
        7200,
        600,
    )

    with pytest.raises(DigestError) as raised:
        extractor.extract(VIDEO_URL)

    assert (raised.value.code, raised.value.retryable) == (
        "INSUFFICIENT_TEXT",
        False,
    )


def test_metadata_probe_uses_only_the_strict_command_profile() -> None:
    class Runner:
        def __init__(self) -> None:
            self.argv: list[str] | None = None

        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            self.argv = argv
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"id":"dQw4w9WgXcQ","title":"公開影片"}',
                stderr="",
            )

    runner = Runner()

    metadata = YtDlpMetadataProbe(runner)(VIDEO_URL)

    assert runner.argv == [
        "yt-dlp",
        "--ignore-config",
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        VIDEO_URL,
    ]
    assert metadata == {"id": "dQw4w9WgXcQ", "title": "公開影片"}


@pytest.mark.parametrize("stdout", ["SECRET_NOT_JSON", '[{"SECRET": true}]'])
def test_metadata_probe_sanitizes_malformed_json(stdout: str) -> None:
    class Runner:
        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    with pytest.raises(DigestError) as raised:
        YtDlpMetadataProbe(Runner())(VIDEO_URL)

    assert raised.value.as_dict() == {
        "stage": "extract",
        "code": "INVALID_METADATA",
        "message": "YouTube metadata is invalid",
        "retryable": False,
    }
    assert "SECRET" not in rendered_exception(raised.value)


def test_caption_client_accepts_vtt_and_pins_the_public_connection() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["connect_host"] = request.url.host
        observed["host"] = request.headers["host"]
        observed["sni"] = request.extensions["sni_hostname"]
        observed["accept"] = request.headers["accept"]
        observed["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            headers={"content-type": "text/vtt; charset=utf-8"},
            content=b"WEBVTT\n\ncaption\xff",
        )

    result = YouTubeCaptionClient(
        client_factory=client_for(httpx.MockTransport(handler))
    )("https://captions.example/manual.vtt")

    assert result == "WEBVTT\n\ncaption�"
    assert observed == {
        "connect_host": "93.184.216.34",
        "host": "captions.example",
        "sni": "captions.example",
        "accept": "text/vtt,text/plain",
        "timeout": {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0},
    }


def test_caption_client_accepts_plain_text() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, text="plain caption"
        )
    )

    assert YouTubeCaptionClient(client_for(transport))(
        "https://captions.example/manual"
    ) == "plain caption"


def test_caption_client_rejects_private_redirect() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302, headers={"location": "http://127.0.0.1/private.vtt"}
        )
    )

    with pytest.raises(DigestError) as raised:
        YouTubeCaptionClient(client_for(transport))(
            "https://captions.example/manual.vtt"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "UNSAFE_DESTINATION",
        False,
    )


def test_caption_client_rejects_response_over_two_mib() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/vtt"},
            content=b"x" * (2 * 1024 * 1024 + 1),
        )
    )

    with pytest.raises(DigestError) as raised:
        YouTubeCaptionClient(client_for(transport))(
            "https://captions.example/manual.vtt"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "RESPONSE_TOO_LARGE",
        False,
    )


def test_caption_client_rejects_non_caption_content_type() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, text="SECRET_HTML"
        )
    )

    with pytest.raises(DigestError) as raised:
        YouTubeCaptionClient(client_for(transport))(
            "https://captions.example/manual.vtt"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "INVALID_CONTENT_TYPE",
        False,
    )
    assert "SECRET_HTML" not in rendered_exception(raised.value)


def test_caption_client_rejects_more_than_three_redirects() -> None:
    redirects = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal redirects
        redirects += 1
        return httpx.Response(302, headers={"location": f"/redirect-{redirects}.vtt"})

    with pytest.raises(DigestError) as raised:
        YouTubeCaptionClient(client_for(httpx.MockTransport(handler)))(
            "https://captions.example/manual.vtt"
        )

    assert redirects == 4
    assert (raised.value.code, raised.value.retryable) == (
        "TOO_MANY_REDIRECTS",
        False,
    )


def test_caption_client_maps_timeout_to_retryable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("SECRET_TIMEOUT", request=request)

    with pytest.raises(DigestError) as raised:
        YouTubeCaptionClient(client_for(httpx.MockTransport(handler)))(
            "https://captions.example/manual.vtt"
        )

    assert (raised.value.code, raised.value.retryable) == (
        "NETWORK_TIMEOUT",
        True,
    )
    assert "SECRET_TIMEOUT" not in rendered_exception(raised.value)


@pytest.mark.parametrize("status_code,retryable", [(404, False), (429, True), (503, True)])
def test_caption_client_maps_http_failures(
    status_code: int, retryable: bool
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, text="SECRET_HTTP_BODY")
    )

    with pytest.raises(DigestError) as raised:
        YouTubeCaptionClient(client_for(transport))(
            "https://captions.example/manual.vtt"
        )

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "extract",
        "HTTP_ERROR",
        retryable,
    )
    assert "SECRET_HTTP_BODY" not in rendered_exception(raised.value)
