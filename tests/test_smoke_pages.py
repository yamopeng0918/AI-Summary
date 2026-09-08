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
            None,
            {"attempts": 6, "delay_seconds": 10, "timeout_seconds": 15},
        )
    ]
    assert capsys.readouterr().err == "homepage failed\n"

    monkeypatch.setattr(smoke_pages, "check_pages", lambda *_args, **_options: [])
    assert smoke_pages.main([]) == 0


def test_default_check_discovers_current_cards_instead_of_archived_demo() -> None:
    calls = []
    responses = {
        "https://example.test/AI-Summary/": (
            '<title>AI Digest</title><article data-summary-card="new-post"></article>'
            "<article data-summary-card='中文&amp;筆記'></article>"
            '<article data-summary-card="new-post"></article>'
        ),
        "https://example.test/AI-Summary/summaries/new-post/": "AI Digest",
        "https://example.test/AI-Summary/summaries/%E4%B8%AD%E6%96%87%26%E7%AD%86%E8%A8%98/": "AI Digest",
    }

    def fetch(url):
        calls.append(url)
        return responses[url]

    assert check_pages("https://example.test/AI-Summary", attempts=1, fetch=fetch) == []
    assert calls == list(responses)


def test_default_check_accepts_explicit_empty_site() -> None:
    calls = []

    def fetch(url):
        calls.append(url)
        return '<title>AI Digest</title><p id="no-data">目前還沒有已發布的摘要。</p>'

    assert check_pages("https://example.test/", attempts=1, fetch=fetch) == []
    assert calls == ["https://example.test/"]


def test_default_check_retries_missing_list_then_checks_discovered_detail() -> None:
    responses = iter([
        "AI Digest",
        '<title>AI Digest</title><article data-summary-card="current"></article>',
        "AI Digest",
    ])
    sleeps = []
    assert check_pages(
        "https://example.test/", attempts=2, delay_seconds=1,
        fetch=lambda _: next(responses), sleep=sleeps.append,
    ) == []
    assert sleeps == [1]


def test_default_check_rejects_homepage_without_list_or_empty_state() -> None:
    assert check_pages("https://example.test/", attempts=1, fetch=lambda _: "AI Digest") == [
        "homepage failed after 1 attempts: missing summary cards or empty-state marker"
    ]


def test_default_check_reports_missing_detail_and_continues_other_cards() -> None:
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith('/summaries/missing/'):
            raise OSError('not found')
        if url.endswith('/summaries/valid/'):
            return 'AI Digest'
        return 'AI Digest<article data-summary-card="missing"></article><article data-summary-card="valid"></article>'

    assert check_pages("https://example.test/", attempts=1, fetch=fetch) == [
        "summary page missing failed after 1 attempts: not found"
    ]
    assert calls[-1].endswith('/summaries/valid/')


def test_default_check_rejects_wrong_detail_content() -> None:
    responses = iter(['AI Digest<article data-summary-card="current"></article>', 'Other site'])
    assert check_pages("https://example.test/", attempts=1, fetch=lambda _: next(responses)) == [
        "summary page current failed after 1 attempts: missing AI Digest marker"
    ]


def test_main_preserves_explicit_demo_id_override(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(smoke_pages, 'check_pages', lambda *args, **kwargs: calls.append(args) or [])
    assert smoke_pages.main(['--demo-id', 'chosen']) == 0
    assert calls == [(smoke_pages.DEFAULT_SITE_ROOT, 'chosen')]
