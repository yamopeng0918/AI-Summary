from pathlib import Path
import subprocess

import pytest

from scripts.verify_deployment import (
    main,
    scan_sensitive_files,
    tracked_paths,
    verify_generated_links,
)


def test_tracked_paths_supports_utf8_filenames(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        ["git", "ls-files", "-z"],
        0,
        stdout="data/summaries/中文摘要.json\0".encode(),
        stderr=b"",
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert tracked_paths() == [Path("data/summaries/中文摘要.json")]
    assert calls == [
        (["git", "ls-files", "-z"], {"check": True, "capture_output": True})
    ]


def test_tracked_paths_propagates_git_failure_without_text_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = subprocess.CalledProcessError(
        128,
        ["git", "ls-files", "-z"],
        stderr="fatal: 中文路徑".encode(),
    )

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise failure

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        tracked_paths()

    assert raised.value is failure


def test_sensitive_scan_flags_real_token_shapes(tmp_path: Path) -> None:
    leaked = tmp_path / "leaked.txt"
    leaked.write_text("OPENAI_API_KEY=sk-proj-" + "A" * 32, encoding="utf-8")

    assert scan_sensitive_files([leaked]) == [f"{leaked}: OpenAI API key"]


def test_sensitive_scan_allows_documented_placeholders(tmp_path: Path) -> None:
    example = tmp_path / "README.md"
    example.write_text("OPENAI_API_KEY=<your-openai-api-key>", encoding="utf-8")

    assert scan_sensitive_files([example]) == []


@pytest.mark.parametrize(
    "token",
    [
        "ghp_" + "A" * 32,
        "github_pat_" + "A" * 32,
    ],
)
def test_sensitive_scan_flags_github_token_forms(tmp_path: Path, token: str) -> None:
    leaked = tmp_path / "leaked.txt"
    leaked.write_text(token, encoding="utf-8")

    assert scan_sensitive_files([leaked]) == [f"{leaked}: GitHub token"]


def test_sensitive_scan_flags_private_key_headers(tmp_path: Path) -> None:
    leaked = tmp_path / "private.pem"
    leaked.write_text("-----BEGIN " + "PRIVATE KEY-----", encoding="utf-8")

    assert scan_sensitive_files([leaked]) == [f"{leaked}: private key"]


def test_sensitive_scan_flags_a_tracked_dot_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SAFE_PLACEHOLDER=", encoding="utf-8")

    assert scan_sensitive_files([env_file]) == [f"{env_file}: tracked .env file"]


def test_sensitive_scan_skips_binary_files_with_nul_bytes(tmp_path: Path) -> None:
    binary = tmp_path / "asset.bin"
    binary.write_bytes(b"\x00sk-proj-" + b"A" * 32)

    assert scan_sensitive_files([binary]) == []


def test_generated_links_reject_root_relative_internal_urls(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text('<a href="/summaries/demo/">Demo</a>', encoding="utf-8")

    assert verify_generated_links(tmp_path, "/AI-Summary/") == [
        f"{index}: internal href /summaries/demo/ misses /AI-Summary/"
    ]


def test_generated_links_accept_pages_base_and_external_urls(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(
        '<a href="/AI-Summary/summaries/demo/">Demo</a>'
        '<a href="https://example.com/article">Source</a>',
        encoding="utf-8",
    )

    assert verify_generated_links(tmp_path, "/AI-Summary/") == []


def test_generated_links_checks_nested_html_files(tmp_path: Path) -> None:
    nested = tmp_path / "summaries" / "demo" / "index.html"
    nested.parent.mkdir(parents=True)
    nested.write_text('<a href="/about/">About</a>', encoding="utf-8")

    assert verify_generated_links(tmp_path, "/AI-Summary/") == [
        f"{nested}: internal href /about/ misses /AI-Summary/"
    ]


def test_generated_links_allows_non_root_internal_and_approved_schemes(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(
        '<a href="summaries/demo/">Relative</a>'
        '<a href="#content">Fragment</a>'
        '<a href="mailto:editor@example.com">Email</a>'
        '<a href="tel:+886123456789">Telephone</a>',
        encoding="utf-8",
    )

    assert verify_generated_links(tmp_path, "/AI-Summary/") == []


def test_generated_links_reports_a_missing_dist_directory(tmp_path: Path) -> None:
    missing = tmp_path / "dist"

    assert verify_generated_links(missing, "/AI-Summary/") == [
        f"{missing}: distribution directory is missing"
    ]


@pytest.mark.parametrize(
    ("relative_path", "contents", "violation"),
    [
        (
            Path("assets") / "app.js",
            "const key = 'sk-proj-" + "A" * 32 + "';",
            "OpenAI API key",
        ),
        (
            Path("index.html"),
            "<!-- github_pat_" + "A" * 32 + " -->",
            "GitHub token",
        ),
        (
            Path("keys") / "private.txt",
            "-----BEGIN " + "PRIVATE KEY-----",
            "private key",
        ),
        (
            Path("config") / ".env",
            "SAFE_PLACEHOLDER=",
            "tracked .env file",
        ),
    ],
)
def test_dist_cli_recursively_rejects_sensitive_generated_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    relative_path: Path,
    contents: str,
    violation: str,
) -> None:
    leaked = tmp_path / relative_path
    leaked.parent.mkdir(parents=True, exist_ok=True)
    leaked.write_text(contents, encoding="utf-8")

    assert main(["--dist", str(tmp_path), "--base", "/AI-Summary/"]) == 1
    assert capsys.readouterr().err == f"{leaked}: {violation}\n"
