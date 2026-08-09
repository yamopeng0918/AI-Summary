from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_SITE_ROOT = "https://yamopeng0918.github.io/AI-Summary/"
DEFAULT_DEMO_ID = "20260809-fictional-ai-digest-demo"
USER_AGENT = "AI-Digest-Pages-Smoke-Checker/1.0"


def fetch_page(url: str, timeout_seconds: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def check_pages(
    site_root: str,
    demo_id: str,
    *,
    attempts: int = 6,
    delay_seconds: float = 10,
    timeout_seconds: float = 15,
    fetch: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    site_root = f"{site_root.rstrip('/')}/"
    homepage_url = site_root
    demo_url = f"{site_root}summaries/{quote(demo_id, safe='')}/"
    fetch_url = fetch or (lambda url: fetch_page(url, timeout_seconds))

    errors = []
    for label, url, marker in (
        ("homepage", homepage_url, "AI Digest"),
        ("demo page", demo_url, None),
    ):
        last_error = "no attempts configured"
        for attempt in range(1, attempts + 1):
            try:
                html = fetch_url(url)
                if marker is not None and marker not in html:
                    raise ValueError(f"missing {marker} marker")
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
    parser.add_argument("--demo-id", default=DEFAULT_DEMO_ID)
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
