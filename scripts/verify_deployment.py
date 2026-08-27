"""Verify tracked files and generated HTML before deployment."""

from argparse import ArgumentParser
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


SENSITIVE_PATTERNS = {
    "OpenAI API key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
    ),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPECTED_OG_IMAGE_DIMENSIONS = (1200, 630)
GITHUB_PAGES_HOST = "yamopeng0918.github.io"


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.image_references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() == "href" and value is not None:
                self.hrefs.append(value.strip())

        attributes = {
            name.lower(): value.strip()
            for name, value in attrs
            if value is not None
        }
        if tag.lower() == "img" and (src := attributes.get("src")) is not None:
            self.image_references.append(src)
        if tag.lower() == "meta" and (content := attributes.get("content")) is not None:
            if attributes.get("property", "").lower() == "og:image":
                self.image_references.append(content)
            if attributes.get("name", "").lower() == "twitter:image":
                self.image_references.append(content)


def scan_sensitive_files(paths: Iterable[Path]) -> list[str]:
    """Return violations for tracked environment files and credential shapes."""
    violations: list[str] = []
    for path in paths:
        if path.name == ".env":
            violations.append(f"{path}: tracked .env file")

        contents = path.read_bytes()
        if b"\x00" in contents:
            continue
        text = contents.decode("utf-8", errors="replace")
        for name, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{path}: {name}")
    return violations


def verify_generated_links(dist_root: Path, base_path: str) -> list[str]:
    """Return root-relative links that do not start with the approved Pages base."""
    if not dist_root.is_dir():
        return [f"{dist_root}: distribution directory is missing"]

    violations: list[str] = []
    approved_base = "/" + base_path.strip("/")
    if approved_base != "/":
        approved_base += "/"
    resolved_dist_root = dist_root.resolve()

    for html_path in sorted(dist_root.rglob("*.html")):
        parser = _HrefParser()
        parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
        for href in parser.hrefs:
            lower_href = href.lower()
            if (
                not href
                or href.startswith("#")
                or lower_href.startswith(("http:", "https:", "mailto:", "tel:"))
                or href.startswith(base_path)
                or not href.startswith("/")
            ):
                continue
            violations.append(
                f"{html_path}: internal href {href} misses {base_path}"
            )

        for reference in parser.image_references:
            parsed = urlsplit(reference)
            if parsed.scheme in {"http", "https"}:
                if parsed.hostname != GITHUB_PAGES_HOST:
                    continue
                reference_path = parsed.path
            elif parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
                continue
            else:
                reference_path = parsed.path

            if not reference_path.startswith(approved_base):
                continue

            image_path = (dist_root / Path(unquote(reference_path[len(approved_base) :]))).resolve()
            try:
                image_path.relative_to(resolved_dist_root)
            except ValueError:
                violations.append(
                    f"{html_path}: local image {reference} escapes distribution directory"
                )
                continue

            if not image_path.is_file():
                violations.append(f"{html_path}: local image {reference} is missing")
                continue

            with image_path.open("rb") as image_file:
                header = image_file.read(24)
            if header[:8] != PNG_SIGNATURE:
                violations.append(f"{html_path}: local image {reference} is not a PNG")
                continue
            if len(header) < 24 or header[8:16] != b"\x00\x00\x00\rIHDR":
                violations.append(
                    f"{html_path}: local image {reference} has a truncated PNG IHDR"
                )
                continue

            dimensions = (
                int.from_bytes(header[16:20], "big"),
                int.from_bytes(header[20:24], "big"),
            )
            if dimensions != EXPECTED_OG_IMAGE_DIMENSIONS:
                violations.append(
                    f"{html_path}: local image {reference} must be 1200x630 PNG "
                    f"(found {dimensions[0]}x{dimensions[1]})"
                )
    return violations


def tracked_paths() -> list[Path]:
    """Return Git-tracked paths without display quoting or locale decoding."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        Path(raw_path.decode("utf-8", errors="surrogateescape"))
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--tracked", action="store_true", help="scan Git-tracked files")
    parser.add_argument("--dist", type=Path, help="verify generated HTML under this directory")
    parser.add_argument("--base", default="/", help="approved root-relative base path")
    args = parser.parse_args(argv)

    violations: list[str] = []
    if args.tracked:
        violations.extend(scan_sensitive_files(tracked_paths()))
    if args.dist is not None:
        violations.extend(
            scan_sensitive_files(
                path for path in sorted(args.dist.rglob("*")) if path.is_file()
            )
        )
        violations.extend(verify_generated_links(args.dist, args.base))

    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
