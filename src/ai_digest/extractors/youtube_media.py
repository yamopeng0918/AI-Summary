"""Safe local media-tool boundary for public YouTube audio."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
import shutil
import subprocess
import tempfile

from ai_digest.domain import DigestError


_PROHIBITED_OPTIONS = frozenset(
    {
        "-p",
        "-u",
        "--client-certificate",
        "--client-certificate-key",
        "--client-certificate-password",
        "--config-locations",
        "--cookies",
        "--cookies-from-browser",
        "--geo-bypass",
        "--geo-bypass-country",
        "--geo-bypass-ip-block",
        "--geo-verification-proxy",
        "--netrc",
        "--netrc-cmd",
        "--netrc-location",
        "--password",
        "--proxy",
        "--twofactor",
        "--username",
        "--video-password",
        "--xff",
    }
)

_LOGIN_REQUIRED_MARKERS = (
    "confirm your age",
    "cookies-from-browser",
    "login required",
    "log in to",
    "sign in",
)
_CONTENT_UNAVAILABLE_MARKERS = (
    "has been removed",
    "members-only",
    "not made this video available in your country",
    "not available in your country",
    "this video is private",
    "video unavailable",
)


class _MediaToolFailure(Exception):
    """Sanitized internal classification for non-retryable tool failures."""

    def __init__(
        self,
        code: Literal["LOGIN_REQUIRED", "CONTENT_UNAVAILABLE"],
    ) -> None:
        super().__init__("Media access is restricted")
        self.code = code
        self.retryable = False


def _access_failure_code(
    stderr: str | bytes | None,
) -> Literal["LOGIN_REQUIRED", "CONTENT_UNAVAILABLE"] | None:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="ignore")
    normalized = (stderr or "").casefold()
    if any(marker in normalized for marker in _LOGIN_REQUIRED_MARKERS):
        return "LOGIN_REQUIRED"
    if any(marker in normalized for marker in _CONTENT_UNAVAILABLE_MARKERS):
        return "CONTENT_UNAVAILABLE"
    return None


def _validate_argv(argv: list[str]) -> None:
    if not isinstance(argv, list) or not argv or any(
        not isinstance(value, str) for value in argv
    ):
        raise TypeError("Media commands require a non-empty argument list")
    options = {value.partition("=")[0].casefold() for value in argv if value.startswith("-")}
    if options & _PROHIBITED_OPTIONS:
        raise ValueError("Unsafe media tool arguments are not allowed")


def _create_workspace(temp_root: Path | None) -> Path:
    try:
        return Path(tempfile.mkdtemp(prefix="ai-digest-youtube-", dir=temp_root))
    except OSError:
        failure = DigestError(
            "extract",
            "MEDIA_DOWNLOAD_FAILED",
            "Media workspace is unavailable",
            True,
        )
    raise failure from None


class CommandRunner:
    """Run a media tool with a fixed, shell-free subprocess policy."""

    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        _validate_argv(argv)
        failure: DigestError | _MediaToolFailure
        try:
            return subprocess.run(
                argv,
                shell=False,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            failure = DigestError(
                "extract",
                "MEDIA_TOOL_MISSING",
                "Required media tool is unavailable",
                False,
            )
        except subprocess.TimeoutExpired:
            failure = DigestError(
                "extract",
                "MEDIA_DOWNLOAD_FAILED",
                "Media tool timed out",
                True,
            )
        except subprocess.CalledProcessError as error:
            access_code = _access_failure_code(error.stderr)
            if access_code is not None:
                failure = _MediaToolFailure(access_code)
            else:
                failure = DigestError(
                    "extract",
                    "MEDIA_DOWNLOAD_FAILED",
                    "Media download or conversion failed",
                    True,
                )
        raise failure from None


class YouTubeMediaPipeline:
    """Download and segment YouTube audio inside an isolated workspace."""

    def __init__(self, runner: CommandRunner, temp_root: Path | None = None) -> None:
        self._runner = runner
        self._temp_root = temp_root

    @contextmanager
    def audio_chunks(self, url: str, chunk_seconds: int) -> Iterator[list[Path]]:
        directory = _create_workspace(self._temp_root)
        try:
            self._runner.run(
                [
                    "yt-dlp",
                    "--ignore-config",
                    "--no-playlist",
                    "-f",
                    "bestaudio",
                    "-P",
                    str(directory),
                    "-o",
                    "source.%(ext)s",
                    url,
                ]
            )
            source = next(directory.glob("source.*"), None)
            if source is None:
                raise DigestError(
                    "extract",
                    "MEDIA_DOWNLOAD_FAILED",
                    "Media download produced no audio",
                    True,
                )

            pattern = directory / "chunk-%04d.mp3"
            self._runner.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-f",
                    "segment",
                    "-segment_time",
                    str(chunk_seconds),
                    str(pattern),
                ]
            )
            chunks = sorted(directory.glob("chunk-*.mp3"))
            if not chunks:
                raise DigestError(
                    "extract",
                    "MEDIA_DOWNLOAD_FAILED",
                    "Media conversion produced no audio",
                    True,
                )
            yield chunks
        finally:
            shutil.rmtree(directory, ignore_errors=True)
