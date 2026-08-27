"""Verify tracked files and generated HTML before deployment."""

from argparse import ArgumentParser
from collections.abc import Iterable, Sequence
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit
import zlib


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
MAX_PNG_CHUNK_BYTES = 16_777_216
MAX_PNG_FILE_BYTES = 33_554_432
MAX_PNG_CHUNKS = 4096

PNG_COLOR_CHANNELS = {
    0: 1,
    2: 3,
    3: 1,
    4: 2,
    6: 4,
}
PNG_VALID_BIT_DEPTHS = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}

SUMMARY_METADATA_KEYS = (
    "og:title",
    "og:description",
    "og:type",
    "og:url",
    "og:image",
    "og:image:width",
    "og:image:height",
    "og:image:alt",
    "twitter:card",
    "twitter:title",
    "twitter:description",
    "twitter:image",
)


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.image_references: list[str] = []
        self.canonical_links: list[tuple[str, str]] = []
        self.metadata: dict[str, list[tuple[str, str]]] = {}
        self.card_images: list[tuple[dict[str, str], str | None, str]] = []
        self._current_anchor_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        raw_tag = self.get_starttag_text()
        normalized_attrs = {
            name.lower(): value.strip()
            for name, value in attrs
            if value is not None
        }
        for name, value in attrs:
            if name.lower() == "href" and value is not None:
                self.hrefs.append(value.strip())

        if tag == "a":
            self._current_anchor_href = normalized_attrs.get("href")

        if tag == "link" and "canonical" in normalized_attrs.get("rel", "").lower().split():
            for name, value in attrs:
                if name.lower() == "href" and value is not None:
                    self.canonical_links.append((value.strip(), raw_tag))

        if tag == "img":
            image_sources = [
                value.strip()
                for name, value in attrs
                if name.lower() == "src" and value is not None
            ]
            self.image_references.extend(image_sources)
            if "summary-card-image" in normalized_attrs.get("class", "").split():
                for source in image_sources:
                    self.card_images.append(
                        (
                            {**normalized_attrs, "src": source},
                            self._current_anchor_href,
                            raw_tag,
                        )
                    )

        if tag == "meta" and any(
            value is not None
            and (
                (name.lower() == "property" and value.lower() == "og:image")
                or (name.lower() == "name" and value.lower() == "twitter:image")
            )
            for name, value in attrs
        ):
            self.image_references.extend(
                value.strip()
                for name, value in attrs
                if name.lower() == "content" and value is not None
            )

        if tag == "meta":
            metadata_names = [
                value.lower()
                for name, value in attrs
                if value is not None and name.lower() in {"name", "property"}
            ]
            metadata_values = [
                value.strip()
                for name, value in attrs
                if value is not None and name.lower() == "content"
            ]
            for metadata_name in metadata_names:
                if metadata_name in SUMMARY_METADATA_KEYS:
                    self.metadata.setdefault(metadata_name, []).extend(
                        (value, raw_tag) for value in metadata_values
                    )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._current_anchor_href = None


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
    """Return href and local generated-image violations in generated HTML."""
    if not dist_root.is_dir():
        return [f"{dist_root}: distribution directory is missing"]

    violations: list[str] = []
    approved_base = "/" + base_path.replace("\\", "/").strip("/")
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
            try:
                parsed = urlsplit(reference.replace("\\", "/"))
                if parsed.scheme in {"http", "https"}:
                    if parsed.hostname != GITHUB_PAGES_HOST:
                        continue
                    reference_path = parsed.path
                elif parsed.netloc:
                    if parsed.hostname != GITHUB_PAGES_HOST:
                        continue
                    reference_path = parsed.path
                elif parsed.scheme or not parsed.path.startswith("/"):
                    continue
                else:
                    reference_path = parsed.path
            except ValueError:
                violations.append(f"{html_path}: malformed image reference")
                continue

            reference_path = unquote(reference_path).replace("\\", "/")

            if not reference_path.startswith(approved_base):
                violations.append(
                    f"{html_path}: image reference {reference} misses {base_path}"
                )
                continue

            image_path = (dist_root / Path(reference_path[len(approved_base) :])).resolve()
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

            dimensions, png_error = _validate_png(image_path)
            if png_error is not None:
                violations.append(
                    f"{html_path}: local image {reference} {png_error}"
                )
                continue
            assert dimensions is not None
            if dimensions != EXPECTED_OG_IMAGE_DIMENSIONS:
                violations.append(
                    f"{html_path}: local image {reference} must be 1200x630 PNG "
                    f"(found {dimensions[0]}x{dimensions[1]})"
                )
    return violations


def _attribute_is_safely_escaped(
    raw_tag: str,
    attribute_name: str,
    decoded_value: str,
) -> bool:
    match = re.search(
        rf"\b{re.escape(attribute_name)}\s*=\s*([\"'])(.*?)\1",
        raw_tag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return False
    raw_value = match.group(2)
    if unescape(raw_value) != decoded_value:
        return False
    without_entities = re.sub(
        r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);",
        "",
        raw_value,
    )
    return not any(character in without_entities for character in "&<>")


def verify_generated_summary_artifacts(
    dist_root: Path,
    base_path: str,
) -> list[str]:
    """Return built summary metadata and homepage-card artifact violations."""
    if not dist_root.is_dir():
        return []

    approved_base = "/" + base_path.replace("\\", "/").strip("/")
    if approved_base != "/":
        approved_base += "/"

    summaries_root = dist_root / "summaries"
    detail_paths = (
        sorted(summaries_root.glob("*/index.html"))
        if summaries_root.is_dir()
        else []
    )
    if not detail_paths:
        return []

    violations: list[str] = []
    expected_cards: dict[str, tuple[Path, str, str]] = {}
    for detail_path in detail_paths:
        parser = _HrefParser()
        parser.feed(detail_path.read_text(encoding="utf-8", errors="replace"))
        summary_id = detail_path.parent.name
        encoded_id = quote(summary_id, safe="")
        expected_page_path = f"{approved_base}summaries/{encoded_id}/"
        expected_image_path = f"{approved_base}og/{encoded_id}.png"
        expected_page_url = f"https://{GITHUB_PAGES_HOST}{expected_page_path}"
        expected_image_url = f"https://{GITHUB_PAGES_HOST}{expected_image_path}"

        canonical_url: str | None = None
        if len(parser.canonical_links) != 1:
            violations.append(
                f"{detail_path}: expected exactly one canonical link "
                f"(found {len(parser.canonical_links)})"
            )
        else:
            canonical_url, raw_tag = parser.canonical_links[0]
            if not _attribute_is_safely_escaped(raw_tag, "href", canonical_url):
                violations.append(
                    f"{detail_path}: canonical href is not safely HTML-escaped"
                )

        metadata_values: dict[str, str] = {}
        for metadata_name in SUMMARY_METADATA_KEYS:
            entries = parser.metadata.get(metadata_name, [])
            if len(entries) != 1:
                violations.append(
                    f"{detail_path}: expected exactly one {metadata_name} metadata value "
                    f"(found {len(entries)})"
                )
                continue
            value, raw_tag = entries[0]
            metadata_values[metadata_name] = value
            if not _attribute_is_safely_escaped(raw_tag, "content", value):
                violations.append(
                    f"{detail_path}: metadata {metadata_name} content is not safely "
                    "HTML-escaped"
                )

        url_values = {
            "canonical": canonical_url,
            "og:url": metadata_values.get("og:url"),
            "og:image": metadata_values.get("og:image"),
            "twitter:image": metadata_values.get("twitter:image"),
        }
        valid_url_names: set[str] = set()
        for url_name, value in url_values.items():
            if value is None:
                continue
            try:
                parsed = urlsplit(value)
                is_absolute_https = (
                    parsed.scheme == "https"
                    and parsed.hostname is not None
                    and parsed.netloc != ""
                )
            except ValueError:
                is_absolute_https = False
                parsed = None
            if not is_absolute_https:
                label = "canonical" if url_name == "canonical" else f"metadata {url_name}"
                violations.append(
                    f"{detail_path}: {label} must be an absolute HTTPS URL"
                )
                continue
            assert parsed is not None
            valid_url_names.add(url_name)
            if parsed.hostname != GITHUB_PAGES_HOST:
                label = "canonical" if url_name == "canonical" else f"metadata {url_name}"
                violations.append(
                    f"{detail_path}: {label} must use {GITHUB_PAGES_HOST}"
                )

        if "canonical" in valid_url_names and canonical_url != expected_page_url:
            violations.append(
                f"{detail_path}: canonical must resolve to {expected_page_url}"
            )
        if "og:url" in valid_url_names and metadata_values["og:url"] != expected_page_url:
            violations.append(
                f"{detail_path}: metadata og:url must resolve to {expected_page_url}"
            )
        for image_metadata_name in ("og:image", "twitter:image"):
            if (
                image_metadata_name in valid_url_names
                and metadata_values[image_metadata_name] != expected_image_url
            ):
                violations.append(
                    f"{detail_path}: metadata {image_metadata_name} must resolve to "
                    f"{expected_image_url}"
                )

        expected_literals = {
            "og:type": "article",
            "og:image:width": "1200",
            "og:image:height": "630",
            "twitter:card": "summary_large_image",
        }
        for metadata_name, expected_value in expected_literals.items():
            value = metadata_values.get(metadata_name)
            if value is not None and value != expected_value:
                violations.append(
                    f"{detail_path}: metadata {metadata_name} must be {expected_value}"
                )
        for open_graph_name, twitter_name in (
            ("og:title", "twitter:title"),
            ("og:description", "twitter:description"),
        ):
            if (
                open_graph_name in metadata_values
                and twitter_name in metadata_values
                and metadata_values[open_graph_name] != metadata_values[twitter_name]
            ):
                violations.append(
                    f"{detail_path}: metadata {open_graph_name} and {twitter_name} must match"
                )

        expected_cards[expected_image_path] = (
            detail_path,
            expected_page_path,
            metadata_values.get("og:image:alt", ""),
        )

    homepage_path = dist_root / "index.html"
    if not homepage_path.is_file():
        violations.append(f"{homepage_path}: generated homepage is missing")
        homepage_parser = _HrefParser()
    else:
        homepage_parser = _HrefParser()
        homepage_parser.feed(
            homepage_path.read_text(encoding="utf-8", errors="replace")
        )

    matched_card_sources: set[str] = set()
    for card_attrs, card_href, raw_tag in homepage_parser.card_images:
        source = card_attrs.get("src", "")
        if source.startswith(approved_base):
            image_path = dist_root / Path(unquote(source[len(approved_base) :]))
            if not image_path.is_file():
                violations.append(f"{homepage_path}: card image {source} is missing")
            else:
                _, png_error = _validate_png(image_path)
                if png_error is not None:
                    violations.append(
                        f"{homepage_path}: card image {source} {png_error}"
                    )
        else:
            violations.append(
                f"{homepage_path}: card image {source} misses {base_path}"
            )

        expected_attributes = {
            "width": "1200",
            "height": "630",
            "loading": "lazy",
            "decoding": "async",
        }
        for attribute_name, expected_value in expected_attributes.items():
            if card_attrs.get(attribute_name) != expected_value:
                violations.append(
                    f"{homepage_path}: card image {source} must use "
                    f"{attribute_name}={expected_value}"
                )
        alt = card_attrs.get("alt", "")
        if not alt:
            violations.append(f"{homepage_path}: card image {source} must have non-empty alt")
        elif not _attribute_is_safely_escaped(raw_tag, "alt", alt):
            violations.append(
                f"{homepage_path}: card image {source} alt is not safely HTML-escaped"
            )

        expected_card = expected_cards.get(source)
        if expected_card is None:
            violations.append(
                f"{homepage_path}: card image {source} does not match a published summary"
            )
            continue
        detail_path, expected_href, expected_alt = expected_card
        if source in matched_card_sources:
            violations.append(f"{homepage_path}: duplicate card image {source}")
            continue
        matched_card_sources.add(source)
        if card_href != expected_href:
            violations.append(
                f"{homepage_path}: card image {source} must link to {expected_href}"
            )
        if alt != expected_alt:
            violations.append(
                f"{homepage_path}: card image {source} alt must match {detail_path} metadata"
            )

    for source, (detail_path, _, _) in expected_cards.items():
        if source not in matched_card_sources:
            violations.append(
                f"{detail_path}: published summary has no matching homepage card image"
            )

    return violations


def _png_scanline_lengths(
    width: int,
    height: int,
    bits_per_pixel: int,
    interlace: int,
) -> list[int]:
    if interlace == 0:
        return [((width * bits_per_pixel + 7) // 8)] * height

    lengths: list[int] = []
    for x_start, y_start, x_step, y_step in (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    ):
        pass_width = max(0, (width - x_start + x_step - 1) // x_step)
        pass_height = max(0, (height - y_start + y_step - 1) // y_step)
        if pass_width == 0 or pass_height == 0:
            continue
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        lengths.extend([row_bytes] * pass_height)
    return lengths


def _validate_png(image_path: Path) -> tuple[tuple[int, int] | None, str | None]:
    if image_path.stat().st_size > MAX_PNG_FILE_BYTES:
        return None, f"PNG exceeds {MAX_PNG_FILE_BYTES}-byte file limit"

    with image_path.open("rb") as image_file:
        if image_file.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            return None, "is not a PNG"

        dimensions: tuple[int, int] | None = None
        scanline_lengths: list[int] = []
        expected_decoded_bytes = 0
        decoded = bytearray()
        decompressor: zlib.Decompress | None = None
        seen_ihdr = False
        seen_idat = False
        seen_iend = False
        idat_ended = False
        seen_plte = False
        color_type: int | None = None

        for chunk_index in range(MAX_PNG_CHUNKS):
            length_bytes = image_file.read(4)
            if not length_bytes:
                break
            if len(length_bytes) != 4:
                return dimensions, "has a truncated PNG chunk"

            chunk_length = int.from_bytes(length_bytes, "big")
            if chunk_length > MAX_PNG_CHUNK_BYTES:
                return (
                    dimensions,
                    f"PNG chunk exceeds {MAX_PNG_CHUNK_BYTES}-byte limit",
                )

            chunk_type = image_file.read(4)
            if len(chunk_type) != 4:
                return dimensions, "has a truncated PNG chunk"
            if any(
                byte not in range(ord("A"), ord("Z") + 1)
                and byte not in range(ord("a"), ord("z") + 1)
                for byte in chunk_type
            ):
                return dimensions, "has an invalid PNG chunk type"

            if chunk_index == 0 and chunk_type != b"IHDR":
                return dimensions, "PNG must contain exactly one IHDR first"
            if chunk_type == b"IHDR" and (seen_ihdr or chunk_index != 0):
                return dimensions, "PNG must contain exactly one IHDR first"
            if chunk_type == b"IHDR" and chunk_length != 13:
                return dimensions, "has an invalid PNG IHDR"

            chunk_data = image_file.read(chunk_length)
            chunk_crc = image_file.read(4)
            if len(chunk_data) != chunk_length or len(chunk_crc) != 4:
                suffix = "IHDR" if chunk_type == b"IHDR" else "chunk"
                return dimensions, f"has a truncated PNG {suffix}"
            expected_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
            if int.from_bytes(chunk_crc, "big") != expected_crc:
                return dimensions, f"PNG CRC mismatch in {chunk_type.decode('ascii')}"

            if chunk_type == b"IHDR":
                seen_ihdr = True
                width = int.from_bytes(chunk_data[0:4], "big")
                height = int.from_bytes(chunk_data[4:8], "big")
                bit_depth = chunk_data[8]
                color_type = chunk_data[9]
                compression = chunk_data[10]
                filtering = chunk_data[11]
                interlace = chunk_data[12]
                if (
                    width == 0
                    or height == 0
                    or color_type not in PNG_COLOR_CHANNELS
                    or bit_depth not in PNG_VALID_BIT_DEPTHS[color_type]
                    or compression != 0
                    or filtering != 0
                    or interlace not in {0, 1}
                ):
                    return dimensions, "has an invalid PNG IHDR"
                dimensions = (width, height)
                bits_per_pixel = PNG_COLOR_CHANNELS[color_type] * bit_depth
                scanline_lengths = _png_scanline_lengths(
                    width,
                    height,
                    bits_per_pixel,
                    interlace,
                )
                expected_decoded_bytes = sum(
                    1 + row_length for row_length in scanline_lengths
                )
                if expected_decoded_bytes > MAX_PNG_CHUNK_BYTES:
                    return dimensions, "has oversized decoded PNG image data"
            elif chunk_type == b"PLTE":
                if seen_plte or seen_idat or chunk_length == 0 or chunk_length % 3 != 0:
                    return dimensions, "has an invalid PNG PLTE chunk"
                seen_plte = True
            elif chunk_type == b"IDAT":
                if idat_ended:
                    return dimensions, "PNG IDAT chunks must be consecutive"
                if color_type == 3 and not seen_plte:
                    return dimensions, "indexed PNG has no PLTE chunk"
                seen_idat = True
                if decompressor is None:
                    decompressor = zlib.decompressobj()
                try:
                    pending = chunk_data
                    while pending:
                        remaining = expected_decoded_bytes + 1 - len(decoded)
                        if remaining <= 0:
                            return dimensions, "has oversized decoded PNG image data"
                        before = len(pending)
                        decoded.extend(decompressor.decompress(pending, remaining))
                        pending = decompressor.unconsumed_tail
                        if pending and len(pending) == before:
                            return dimensions, "has undecodable PNG image data"
                    if len(decoded) > expected_decoded_bytes:
                        return dimensions, "has oversized decoded PNG image data"
                except zlib.error:
                    return dimensions, "has undecodable PNG image data"
            elif chunk_type == b"IEND":
                if chunk_length != 0:
                    return dimensions, "has an invalid PNG IEND chunk"
                seen_iend = True
                if image_file.read(1):
                    return dimensions, "PNG has data after IEND"
                break
            else:
                if seen_idat:
                    idat_ended = True
                if chunk_type[0] in range(ord("A"), ord("Z") + 1):
                    return dimensions, "has an unknown critical PNG chunk"
        else:
            return dimensions, f"PNG exceeds {MAX_PNG_CHUNKS}-chunk limit"

    if not seen_ihdr:
        return dimensions, "PNG must contain exactly one IHDR first"
    if not seen_idat:
        return dimensions, "PNG has no IDAT chunk"
    if not seen_iend:
        return dimensions, "PNG has no terminal IEND chunk"
    if decompressor is None:
        return dimensions, "has undecodable PNG image data"

    try:
        remaining = expected_decoded_bytes + 1 - len(decoded)
        decoded.extend(decompressor.flush(max(1, remaining)))
    except zlib.error:
        return dimensions, "has undecodable PNG image data"
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or len(decoded) != expected_decoded_bytes
    ):
        return dimensions, "has undecodable PNG image data"

    offset = 0
    for row_length in scanline_lengths:
        if decoded[offset] > 4:
            return dimensions, "has an invalid PNG row filter"
        offset += 1 + row_length
    return dimensions, None


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
        violations.extend(verify_generated_summary_artifacts(args.dist, args.base))

    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
