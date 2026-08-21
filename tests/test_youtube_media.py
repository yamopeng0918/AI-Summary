import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import pytest

from ai_digest.domain import DigestError
from ai_digest.extractors.youtube_media import (
    CommandRunner,
    YouTubeMediaPipeline,
)


VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _formatted_exception(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_command_runner_never_uses_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    CommandRunner().run(["yt-dlp", "--version"])

    assert observed["argv"] == ["yt-dlp", "--version"]
    assert observed["kwargs"] == {
        "shell": False,
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": 300,
    }


def test_command_runner_rejects_command_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> None:
        pytest.fail("subprocess.run must not receive a command string")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    with pytest.raises(TypeError, match="argument list"):
        CommandRunner().run("yt-dlp --version")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "unsafe_argv",
    [
        ["yt-dlp", "--cookies", "cookies.txt", VIDEO_URL],
        ["yt-dlp", "--cookies-from-browser=firefox", VIDEO_URL],
        ["yt-dlp", "--proxy", "http://proxy.invalid", VIDEO_URL],
        ["yt-dlp", "--geo-bypass", VIDEO_URL],
        ["yt-dlp", "--username=user", "--password=secret", VIDEO_URL],
        ["yt-dlp", "-uUSER", "-pPASS", VIDEO_URL],
        ["yt-dlp", "-2CODE", VIDEO_URL],
        ["yt-dlp", "-n", VIDEO_URL],
        ["yt-dlp", "--ap-username=USER", "--ap-password=PASS", VIDEO_URL],
        ["yt-dlp", "--add-headers=Authorization: Bearer SECRET", VIDEO_URL],
        ["yt-dlp", "--add-header", "Cookie: session=SECRET", VIDEO_URL],
        ["yt-dlp", "--impersonate=chrome", VIDEO_URL],
        ["yt-dlp", "--config-locations", "unsafe.conf", VIDEO_URL],
        ["ffmpeg", "-cookies=session=SECRET", "-i", "input"],
        ["ffmpeg", "-headers", "Authorization: Bearer SECRET", "-i", "input"],
        ["ffmpeg", "-http_proxy=http://proxy.invalid", "-i", "input"],
    ],
)
def test_command_runner_rejects_credentials_proxies_and_bypass_flags(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_argv: list[str],
) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> None:
        pytest.fail("unsafe arguments must not reach subprocess.run")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    with pytest.raises(ValueError, match="Unsafe media tool arguments") as raised:
        CommandRunner().run(unsafe_argv)

    assert VIDEO_URL not in str(raised.value)
    assert "secret" not in str(raised.value)


def test_command_runner_maps_missing_executable_without_leaking_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("SECRET_PATH")

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(DigestError) as raised:
        CommandRunner().run(["yt-dlp", "--version"])

    assert raised.value.code == "MEDIA_TOOL_MISSING"
    assert raised.value.retryable is False
    assert "SECRET_PATH" not in raised.value.message
    assert "SECRET_PATH" not in _formatted_exception(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


def test_command_runner_maps_timeout_without_leaking_tool_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            ["yt-dlp", VIDEO_URL, "C:\\SECRET_PATH"],
            300,
            output="SECRET_STDOUT",
            stderr="SECRET_STDERR",
        )

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(DigestError) as raised:
        CommandRunner().run(["yt-dlp", VIDEO_URL])

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    rendered = _formatted_exception(raised.value)
    assert VIDEO_URL not in rendered
    assert "SECRET_PATH" not in rendered
    assert "SECRET_STDOUT" not in rendered
    assert "SECRET_STDERR" not in rendered
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


def test_command_runner_maps_transient_nonzero_exit_without_leaking_tool_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            1,
            ["yt-dlp", VIDEO_URL, "C:\\SECRET_PATH"],
            output="SECRET_STDOUT",
            stderr="temporary network failure SECRET_STDERR",
        )

    monkeypatch.setattr(subprocess, "run", failed)

    with pytest.raises(DigestError) as raised:
        CommandRunner().run(["yt-dlp", VIDEO_URL])

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    rendered = _formatted_exception(raised.value)
    assert VIDEO_URL not in rendered
    assert "SECRET_PATH" not in rendered
    assert "SECRET_STDOUT" not in rendered
    assert "SECRET_STDERR" not in rendered
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError("C:\\SECRET_PATH"),
        UnicodeDecodeError(
            "utf-8",
            b"\xffSECRET_OUTPUT",
            0,
            1,
            "SECRET_DECODE_REASON",
        ),
    ],
)
def test_command_runner_sanitizes_os_and_decode_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(subprocess, "run", failed)

    with pytest.raises(DigestError) as raised:
        CommandRunner().run(["yt-dlp", VIDEO_URL])

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    rendered = _formatted_exception(raised.value)
    assert VIDEO_URL not in rendered
    assert "SECRET_PATH" not in rendered
    assert "SECRET_OUTPUT" not in rendered
    assert "SECRET_DECODE_REASON" not in rendered
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("stderr", "expected_code"),
    [
        ("Sign in to confirm your age. SECRET_STDERR", "LOGIN_REQUIRED"),
        ("This video is private. SECRET_STDERR", "CONTENT_UNAVAILABLE"),
        (
            "The uploader has not made this video available in your country. SECRET_STDERR",
            "CONTENT_UNAVAILABLE",
        ),
        (
            "This video is private. Sign in if you've been granted access.",
            "CONTENT_UNAVAILABLE",
        ),
        ("Video unavailable. Sign in to confirm your age.", "LOGIN_REQUIRED"),
        ("This video is unavailable. SECRET_STDERR", "CONTENT_UNAVAILABLE"),
    ],
)
def test_command_runner_returns_safe_access_failure_classification(
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    expected_code: str,
) -> None:
    def restricted(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            1,
            ["yt-dlp", VIDEO_URL, "C:\\SECRET_PATH"],
            output="SECRET_STDOUT",
            stderr=stderr,
        )

    monkeypatch.setattr(subprocess, "run", restricted)

    with pytest.raises(DigestError) as raised:
        CommandRunner().run(["yt-dlp", VIDEO_URL])

    assert raised.value.stage == "extract"
    assert raised.value.code == expected_code
    assert raised.value.retryable is False
    rendered = _formatted_exception(raised.value)
    assert VIDEO_URL not in rendered
    assert "SECRET_PATH" not in rendered
    assert "SECRET_STDOUT" not in rendered
    assert "SECRET_STDERR" not in rendered
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


class CreatingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        directory = (
            Path(argv[argv.index("-P") + 1])
            if "-P" in argv
            else Path(argv[-1]).parent
        )
        if argv[0] == "yt-dlp":
            (directory / "source.webm").write_bytes(b"source")
        else:
            (directory / "chunk-0001.mp3").write_bytes(b"second")
            (directory / "chunk-0000.mp3").write_bytes(b"first")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_audio_chunks_are_ordered_use_safe_flags_and_are_removed(
    tmp_path: Path,
) -> None:
    runner = CreatingRunner()
    pipeline = YouTubeMediaPipeline(runner, temp_root=tmp_path)

    with pipeline.audio_chunks(VIDEO_URL, 600) as chunks:
        directory = chunks[0].parent
        assert directory.parent == tmp_path
        assert directory.name.startswith("ai-digest-youtube-")
        assert directory.exists()
        assert [item.name for item in chunks] == [
            "chunk-0000.mp3",
            "chunk-0001.mp3",
        ]

    yt_dlp, ffmpeg = runner.calls
    assert yt_dlp == [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "-f",
        "bestaudio",
        "-P",
        str(directory),
        "-o",
        "source.%(ext)s",
        VIDEO_URL,
    ]
    assert ffmpeg == [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        str(directory / "source.webm"),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "segment",
        "-segment_time",
        "600",
        str(directory / "chunk-%04d.mp3"),
    ]
    assert not any(
        "cookie" in value.lower()
        or "proxy" in value.lower()
        or "bypass" in value.lower()
        for call in runner.calls
        for value in call
    )
    assert list(tmp_path.iterdir()) == []


def test_audio_chunks_removes_isolated_directory_after_download_failure(
    tmp_path: Path,
) -> None:
    created: list[Path] = []

    class FailingRunner:
        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            created.append(Path(argv[argv.index("-P") + 1]))
            raise DigestError(
                "extract",
                "MEDIA_DOWNLOAD_FAILED",
                "Media download failed",
                True,
            )

    pipeline = YouTubeMediaPipeline(FailingRunner(), temp_root=tmp_path)

    with pytest.raises(DigestError):
        with pipeline.audio_chunks(VIDEO_URL, 600):
            pass

    assert len(created) == 1
    assert not created[0].exists()
    assert list(tmp_path.iterdir()) == []


def test_audio_chunks_maps_workspace_failure_without_leaking_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def failed_workspace(*args: object, **kwargs: object) -> str:
        raise OSError("C:\\SECRET_PATH")

    monkeypatch.setattr(tempfile, "mkdtemp", failed_workspace)
    pipeline = YouTubeMediaPipeline(CreatingRunner(), temp_root=tmp_path)

    with pytest.raises(DigestError) as raised:
        with pipeline.audio_chunks(VIDEO_URL, 600):
            pass

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    assert "SECRET_PATH" not in raised.value.message
    assert "SECRET_PATH" not in _formatted_exception(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


def test_audio_chunks_maps_missing_download_output_and_cleans_up(
    tmp_path: Path,
) -> None:
    class EmptyRunner:
        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    pipeline = YouTubeMediaPipeline(EmptyRunner(), temp_root=tmp_path)

    with pytest.raises(DigestError) as raised:
        with pipeline.audio_chunks(VIDEO_URL, 600):
            pass

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    assert VIDEO_URL not in raised.value.message
    assert list(tmp_path.iterdir()) == []


def test_audio_chunks_maps_missing_conversion_output_and_cleans_up(
    tmp_path: Path,
) -> None:
    class SourceOnlyRunner:
        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            if argv[0] == "yt-dlp":
                directory = Path(argv[argv.index("-P") + 1])
                (directory / "source.webm").write_bytes(b"source")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    pipeline = YouTubeMediaPipeline(SourceOnlyRunner(), temp_root=tmp_path)

    with pytest.raises(DigestError) as raised:
        with pipeline.audio_chunks(VIDEO_URL, 600):
            pass

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert raised.value.retryable is True
    assert VIDEO_URL not in raised.value.message
    assert list(tmp_path.iterdir()) == []


def test_audio_chunks_cleans_up_after_conversion_runner_failure(
    tmp_path: Path,
) -> None:
    created: list[Path] = []

    class ConversionFailingRunner:
        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            if argv[0] == "yt-dlp":
                directory = Path(argv[argv.index("-P") + 1])
                created.append(directory)
                (directory / "source.webm").write_bytes(b"source")
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            raise DigestError(
                "extract",
                "MEDIA_DOWNLOAD_FAILED",
                "Media conversion failed",
                True,
            )

    pipeline = YouTubeMediaPipeline(ConversionFailingRunner(), temp_root=tmp_path)

    with pytest.raises(DigestError) as raised:
        with pipeline.audio_chunks(VIDEO_URL, 600):
            pass

    assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
    assert len(created) == 1
    assert not created[0].exists()
    assert list(tmp_path.iterdir()) == []


def test_audio_chunks_retries_cleanup_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_rmtree = shutil.rmtree
    attempts: list[Path] = []

    def flaky_rmtree(path: Path) -> None:
        attempts.append(Path(path))
        if len(attempts) == 1:
            raise PermissionError("C:\\SECRET_PATH")
        real_rmtree(path)

    monkeypatch.setattr(shutil, "rmtree", flaky_rmtree)
    pipeline = YouTubeMediaPipeline(CreatingRunner(), temp_root=tmp_path)

    with pipeline.audio_chunks(VIDEO_URL, 600):
        pass

    assert len(attempts) == 2
    assert list(tmp_path.iterdir()) == []


def test_audio_chunks_reports_sanitized_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_rmtree = shutil.rmtree
    attempts: list[Path] = []

    def failed_rmtree(path: Path) -> None:
        attempts.append(Path(path))
        raise PermissionError("C:\\SECRET_PATH")

    monkeypatch.setattr(shutil, "rmtree", failed_rmtree)
    pipeline = YouTubeMediaPipeline(CreatingRunner(), temp_root=tmp_path)
    directory: Path | None = None

    try:
        with pytest.raises(DigestError) as raised:
            with pipeline.audio_chunks(VIDEO_URL, 600) as chunks:
                directory = chunks[0].parent

        assert raised.value.code == "MEDIA_DOWNLOAD_FAILED"
        assert raised.value.retryable is True
        assert "SECRET_PATH" not in raised.value.message
        assert "SECRET_PATH" not in _formatted_exception(raised.value)
        assert raised.value.__context__ is None
        assert raised.value.__cause__ is None
        assert len(attempts) == 2
    finally:
        monkeypatch.setattr(shutil, "rmtree", real_rmtree)
        if directory is not None and directory.exists():
            real_rmtree(directory)


def test_audio_chunks_preserves_primary_failure_when_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_rmtree = shutil.rmtree
    attempts: list[Path] = []
    primary = DigestError(
        "extract",
        "MEDIA_DOWNLOAD_FAILED",
        "Primary safe failure",
        True,
    )

    class PrimaryFailingRunner:
        def run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
            raise primary

    def failed_rmtree(path: Path) -> None:
        attempts.append(Path(path))
        raise PermissionError("C:\\SECRET_PATH")

    monkeypatch.setattr(shutil, "rmtree", failed_rmtree)
    pipeline = YouTubeMediaPipeline(PrimaryFailingRunner(), temp_root=tmp_path)

    try:
        with pytest.raises(DigestError) as raised:
            with pipeline.audio_chunks(VIDEO_URL, 600):
                pass

        assert raised.value is primary
        assert raised.value.message == "Primary safe failure"
        assert "SECRET_PATH" not in _formatted_exception(raised.value)
        assert len(attempts) == 2
    finally:
        monkeypatch.setattr(shutil, "rmtree", real_rmtree)
        for directory in tmp_path.iterdir():
            real_rmtree(directory)


@pytest.mark.parametrize("failure", [RuntimeError("stop"), KeyboardInterrupt()])
def test_audio_chunks_cleanup_when_consumer_is_interrupted(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    pipeline = YouTubeMediaPipeline(CreatingRunner(), temp_root=tmp_path)

    with pytest.raises(type(failure)):
        with pipeline.audio_chunks(VIDEO_URL, 600):
            raise failure

    assert list(tmp_path.iterdir()) == []
