from dataclasses import dataclass
from html import unescape
import re


_TRADITIONAL = ("zh-TW", "zh-Hant", "zh-HK")
_TIMING = re.compile(r"^\s*\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->.*$")
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    language: str
    url: str
    automatic: bool


def _rank(track: CaptionTrack, original_language: str | None) -> tuple[int, str]:
    if track.language in _TRADITIONAL:
        return (0, track.language)
    if original_language and track.language == original_language:
        return (1, track.language)
    return (2, track.language)


def select_caption(
    manual: list[CaptionTrack], automatic: list[CaptionTrack], original_language: str | None
) -> CaptionTrack | None:
    candidates = manual if manual else automatic
    return min(candidates, key=lambda item: _rank(item, original_language), default=None)


def normalize_vtt(payload: str) -> str:
    normalized: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or _TIMING.match(line) or line.isdigit():
            continue
        text = unescape(_TAG.sub("", line)).strip()
        if text and (not normalized or normalized[-1] != text):
            normalized.append(text)
    return "\n".join(normalized)
