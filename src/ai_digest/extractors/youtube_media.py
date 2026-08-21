"""Safe local media-tool boundary for public YouTube audio."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
import shutil
import subprocess
import tempfile

from ai_digest.domain import DigestError


_YT_DLP_PROHIBITED_OPTIONS = frozenset(
    {
        "-2",
        "-n",
        "-p",
        "-u",
        "--add-header",
        "--add-headers",
        "--ap-mso",
        "--ap-password",
        "--ap-username",
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
        "--http-header",
        "--http-headers",
        "--impersonate",
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
_YT_DLP_ATTACHED_VALUE_OPTIONS = ("-2", "-p", "-u")
_FFMPEG_PROHIBITED_OPTIONS = frozenset({"-cookies", "-headers", "-http_proxy"})

_LOGIN_REQUIRED_MARKERS = (
    "confirm your age",
    "cookies-from-browser",
    "login required",
    "log in to",
    "sign in",
)
_DEFINITIVE_CONTENT_UNAVAILABLE_MARKERS = (
    "has been removed",
    "members-only",
    "not made this video available in your country",
    "not available in your country",
    "private video",
    "this video is private",
)
_GENERIC_CONTENT_UNAVAILABLE_MARKERS = (
    "this video is unavailable",
    "video is unavailable",
    "video unavailable",
)


def _access_failure_code(
    stderr: str | bytes | None,
) -> Literal["LOGIN_REQUIRED", "CONTENT_UNAVAILABLE"] | None:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="ignore")
    normalized = (stderr or "").casefold()
    if any(
        marker in normalized for marker in _DEFINITIVE_CONTENT_UNAVAILABLE_MARKERS
    ):
        return "CONTENT_UNAVAILABLE"
    if any(marker in normalized for marker in _LOGIN_REQUIRED_MARKERS):
        return "LOGIN_REQUIRED"
    if any(
        marker in normalized for marker in _GENERIC_CONTENT_UNAVAILABLE_MARKERS
    ):
        return "CONTENT_UNAVAILABLE"
    return None


def _validate_argv(argv: list[str]) -> None:
    if not isinstance(argv, list) or not argv or any(
        not isinstance(value, str) for value in argv
    ):
        raise TypeError("Media commands require a non-empty argument list")
    tool = Path(argv[0]).name.casefold().removesuffix(".exe")
    options = {
        value.partition("=")[0].casefold()
        for value in argv[1:]
        if value.startswith("-")
    }
    unsafe = False
    if tool == "yt-dlp":
        unsafe = bool(options & _YT_DLP_PROHIBITED_OPTIONS) or any(
            value.casefold().startswith(prefix) and value.casefold() != prefix
            for value in argv[1:]
            for prefix in _YT_DLP_ATTACHED_VALUE_OPTIONS
        )
    elif tool == "ffmpeg":
        unsafe = bool(options & _FFMPEG_PROHIBITED_OPTIONS)
    if unsafe:
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


def _cleanup_workspace(directory: Path) -> DigestError | None:
    failure: DigestError | None = None
    for _ in range(2):
        try:
            shutil.rmtree(directory)
            return None
        except FileNotFoundError:
            return None
        except OSError:
            failure = DigestError(
                "extract",
                "MEDIA_DOWNLOAD_FAILED",
                "Media workspace cleanup failed",
                True,
            )
    return failure


class CommandRunner:
    """Run a media tool with a fixed, shell-free subprocess policy."""

    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        _validate_argv(argv)
        failure: DigestError
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
        except OSError:
            failure = DigestError(
                "extract",
                "MEDIA_DOWNLOAD_FAILED",
                "Media tool could not be started",
                True,
            )
        except UnicodeError:
            failure = DigestError(
                "extract",
                "MEDIA_DOWNLOAD_FAILED",
                "Media tool output could not be read",
                True,
            )
        except subprocess.CalledProcessError as error:
            access_code = _access_failure_code(error.stderr)
            if access_code is not None:
                message = (
                    "Public media requires authentication"
                    if access_code == "LOGIN_REQUIRED"
                    else "Public media is unavailable"
                )
                failure = DigestError("extract", access_code, message, False)
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
        primary_failure: BaseException | None = None
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
        except BaseException as error:
            primary_failure = error
            raise
        finally:
            cleanup_failure = _cleanup_workspace(directory)
            if cleanup_failure is not None and primary_failure is None:
                raise cleanup_failure from None
