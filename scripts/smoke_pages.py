from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_SITE_ROOT = "https://yamopeng0918.github.io/AI-Summary/"
USER_AGENT = "AI-Digest-Pages-Smoke-Checker/1.0"


class _SummaryListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.summary_ids: list[str] = []
        self.empty = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        record_id = attributes.get("data-summary-card")
        if tag == "article" and record_id and record_id not in self.summary_ids:
            self.summary_ids.append(record_id)
        if tag == "p" and attributes.get("id") == "no-data":
            self.empty = True


def fetch_page(url: str, timeout_seconds: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def check_pages(
    site_root: str,
    demo_id: str | None = None,
    *,
    attempts: int = 6,
    delay_seconds: float = 10,
    timeout_seconds: float = 15,
    fetch: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    site_root = f"{site_root.rstrip('/')}/"
    homepage_url = site_root
    fetch_url = fetch or (lambda url: fetch_page(url, timeout_seconds))

    errors = []
    pages = [("homepage", homepage_url, "AI Digest")]
    if demo_id is not None:
        pages.append(("demo page", f"{site_root}summaries/{quote(demo_id, safe='')}/", None))
    for label, url, marker in pages:
        last_error = "no attempts configured"
        for attempt in range(1, attempts + 1):
            try:
                html = fetch_url(url)
                if marker is not None and marker not in html:
                    raise ValueError(f"missing {marker} marker")
                if label == "homepage" and demo_id is None:
                    parser = _SummaryListParser()
                    parser.feed(html)
                    if not parser.summary_ids and not parser.empty:
                        raise ValueError("missing summary cards or empty-state marker")
                    pages.extend(
                        (f"summary page {record_id}",
                         f"{site_root}summaries/{quote(record_id, safe='')}/", "AI Digest")
                        for record_id in parser.summary_ids
                    )
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < attempts:
                    sleep(delay_seconds)
        else:
            errors.append(f"{label} failed after {attempts} attempts: {last_error}")

    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the public AI Digest Pages deployment.")
    parser.add_argument("--site-root", default=DEFAULT_SITE_ROOT)
    parser.add_argument("--demo-id", help="Check one explicit summary ID instead of discovering current cards.")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--delay-seconds", type=float, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=15)
    args = parser.parse_args(argv)

    errors = check_pages(
        args.site_root,
        args.demo_id,
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
