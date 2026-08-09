from scripts import smoke_pages
from scripts.smoke_pages import check_pages


def test_pages_check_accepts_home_and_demo() -> None:
    responses = {
        "https://example.test/AI-Summary/": "<title>AI Digest</title>",
        "https://example.test/AI-Summary/summaries/demo/": "<h1>Demo</h1>",
    }
    assert check_pages(
        "https://example.test/AI-Summary/",
        "demo",
        attempts=1,
        delay_seconds=0,
        fetch=responses.__getitem__,
        sleep=lambda _: None,
    ) == []


def test_pages_check_retries_then_reports_failure() -> None:
    calls = []

    def failing_fetch(url: str) -> str:
        calls.append(url)
        raise OSError("not ready")

    errors = check_pages(
        "https://example.test/AI-Summary/",
        "demo",
        attempts=3,
        delay_seconds=0,
        fetch=failing_fetch,
        sleep=lambda _: None,
    )
    assert len(calls) == 6
    assert errors == [
        "homepage failed after 3 attempts: not ready",
        "demo page failed after 3 attempts: not ready",
    ]


def test_pages_check_rejects_homepage_without_ai_digest_marker() -> None:
    responses = {
        "https://example.test/AI-Summary/": "<title>Other site</title>",
        "https://example.test/AI-Summary/summaries/demo/": "<h1>Demo</h1>",
    }

    assert check_pages(
        "https://example.test/AI-Summary/",
        "demo",
        attempts=1,
        delay_seconds=0,
        fetch=responses.__getitem__,
        sleep=lambda _: None,
    ) == ["homepage failed after 1 attempts: missing AI Digest marker"]


def test_fetch_page_sends_user_agent_and_timeout(monkeypatch) -> None:
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return b"<title>AI Digest</title>"

    def fake_urlopen(request, *, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr(smoke_pages, "urlopen", fake_urlopen, raising=False)

    assert smoke_pages.fetch_page("https://example.test/", 7) == "<title>AI Digest</title>"
    request, timeout = calls[0]
    assert request.full_url == "https://example.test/"
    assert request.get_header("User-agent") == smoke_pages.USER_AGENT
    assert timeout == 7


def test_main_uses_public_defaults_and_returns_failure(monkeypatch, capsys) -> None:
    calls = []

    def fake_check_pages(site_root, demo_id, **options):
        calls.append((site_root, demo_id, options))
        return ["homepage failed"]

    monkeypatch.setattr(smoke_pages, "check_pages", fake_check_pages)

    assert smoke_pages.main([]) == 1
    assert calls == [
        (
            "https://yamopeng0918.github.io/AI-Summary/",
            "20260809-fictional-ai-digest-demo",
            {"attempts": 6, "delay_seconds": 10, "timeout_seconds": 15},
        )
    ]
    assert capsys.readouterr().err == "homepage failed\n"

    monkeypatch.setattr(smoke_pages, "check_pages", lambda *_args, **_options: [])
    assert smoke_pages.main([]) == 0
