"""Captions-first extraction for public YouTube videos."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle
from ai_digest.extractors.public_http import PublicHttpDownloader
from ai_digest.extractors.youtube_captions import (
    CaptionTrack,
    normalize_vtt,
    select_caption,
)
from ai_digest.extractors.youtube_media import CommandRunner
from ai_digest.transcribers import AudioTranscriber


_MIN_TEXT_LENGTH = 200
_CAPTION_MAX_BYTES = 2 * 1024 * 1024
_CAPTION_MAX_REDIRECTS = 3
_CAPTION_TIMEOUT_SECONDS = 15.0
_CAPTION_CONTENT_TYPES = {"text/vtt", "text/plain"}


def _error(code: str, message: str, retryable: bool) -> DigestError:
    return DigestError("extract", code, message, retryable)


class YtDlpMetadataProbe:
    """Read public YouTube metadata through the strict CommandRunner profile."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def __call__(self, url: str) -> dict[str, Any]:
        result = self._runner.run(
            [
                "yt-dlp",
                "--ignore-config",
                "--dump-single-json",
                "--skip-download",
                "--no-playlist",
                url,
            ]
        )
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            raise _error(
                "INVALID_METADATA", "YouTube metadata is invalid", False
            ) from None
        if not isinstance(value, dict):
            raise _error("INVALID_METADATA", "YouTube metadata is invalid", False)
        return value


class YouTubeCaptionClient:
    """Fetch a bounded caption file through the shared public HTTP boundary."""

    def __init__(self, client_factory: Callable[[], httpx.Client]) -> None:
        self._downloader = PublicHttpDownloader(
            client_factory,
            allowed_content_types=_CAPTION_CONTENT_TYPES,
            invalid_content_type_message=(
                "YouTube caption response has an invalid content type"
            ),
            accept="text/vtt,text/plain",
            max_bytes=_CAPTION_MAX_BYTES,
            max_redirects=_CAPTION_MAX_REDIRECTS,
            timeout=_CAPTION_TIMEOUT_SECONDS,
        )

    def __call__(self, url: str) -> str:
        return self._downloader.get(url).body.decode("utf-8", errors="replace")


class YouTubeExtractor:
    """Return metadata and readable text without summarizing or persisting it."""

    def __init__(
        self,
        probe: Callable[[str], dict[str, Any]],
        caption_client: Callable[[str], str],
        media: Callable[[str, int], AbstractContextManager[list[Path]]],
        transcriber_factory: Callable[[], AudioTranscriber],
        max_duration_seconds: int,
        chunk_seconds: int,
    ) -> None:
        self._probe = probe
        self._caption_client = caption_client
        self._media = media
        self._transcriber_factory = transcriber_factory
        self._max_duration = max_duration_seconds
        self._chunk_seconds = chunk_seconds

    def extract(self, url: str) -> ExtractedArticle:
        metadata = self._safe_probe(url)
        self._validate_availability(metadata)
        track = select_caption(
            self._tracks(metadata.get("subtitles"), automatic=False),
            self._tracks(metadata.get("automatic_captions"), automatic=True),
            metadata.get("language")
            if isinstance(metadata.get("language"), str)
            else None,
        )
        if track is not None:
            text = self._caption_text(track.url)
        else:
            transcriber = self._transcriber_factory()
            with self._media(url, self._chunk_seconds) as chunks:
                text = transcriber.transcribe(chunks)
        if not isinstance(text, str) or len(text) < _MIN_TEXT_LENGTH:
            raise _error(
                "INSUFFICIENT_TEXT",
                "YouTube source does not contain enough text",
                False,
            )
        try:
            return ExtractedArticle(
                canonicalUrl=url,
                sourceType="youtube",
                title=metadata["title"],
                author=metadata.get("channel"),
                publishedAt=self._published_at(metadata.get("upload_date")),
                text=text,
            )
        except (KeyError, TypeError, ValidationError):
            raise _error(
                "INVALID_METADATA", "YouTube metadata is invalid", False
            ) from None

    def _safe_probe(self, url: str) -> dict[str, Any]:
        try:
            metadata = self._probe(url)
        except DigestError:
            raise
        except Exception:
            raise _error(
                "MEDIA_DOWNLOAD_FAILED", "YouTube metadata request failed", True
            ) from None
        if not isinstance(metadata, dict):
            raise _error("INVALID_METADATA", "YouTube metadata is invalid", False)
        return metadata

    def _validate_availability(self, metadata: dict[str, Any]) -> None:
        availability = metadata.get("availability")
        if availability in {"needs_auth", "needs_subscription"}:
            raise _error(
                "LOGIN_REQUIRED", "YouTube source requires login", False
            )
        if availability not in {None, "public", "unlisted"}:
            raise _error(
                "CONTENT_UNAVAILABLE", "YouTube source is unavailable", False
            )
        if metadata.get("live_status") in {"is_live", "is_upcoming"}:
            raise _error(
                "LIVE_STREAM_UNSUPPORTED",
                "Live YouTube sources are unsupported",
                False,
            )
        duration = metadata.get("duration")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
        ):
            raise _error("INVALID_METADATA", "YouTube metadata is invalid", False)
        if duration > self._max_duration:
            raise _error(
                "VIDEO_TOO_LONG",
                "YouTube video exceeds the duration limit",
                False,
            )

    def _caption_text(self, url: str) -> str:
        try:
            payload = self._caption_client(url)
        except DigestError:
            raise
        except Exception:
            raise _error(
                "NETWORK_ERROR", "YouTube caption request failed", True
            ) from None
        if not isinstance(payload, str):
            raise _error(
                "INVALID_METADATA", "YouTube caption data is invalid", False
            )
        try:
            return normalize_vtt(payload)
        except Exception:
            raise _error(
                "INVALID_METADATA", "YouTube caption data is invalid", False
            ) from None

    @staticmethod
    def _tracks(raw: object, *, automatic: bool) -> list[CaptionTrack]:
        if not isinstance(raw, dict):
            return []
        tracks: list[CaptionTrack] = []
        for language, entries in raw.items():
            if not isinstance(language, str) or not isinstance(entries, list):
                continue
            entry = next(
                (
                    item
                    for item in entries
                    if isinstance(item, dict)
                    and item.get("ext") == "vtt"
                    and isinstance(item.get("url"), str)
                ),
                None,
            )
            if entry is not None:
                tracks.append(CaptionTrack(language, entry["url"], automatic))
        return tracks

    @staticmethod
    def _published_at(raw: object) -> datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
