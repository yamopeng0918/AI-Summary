from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_digest import cli
from ai_digest.domain import DigestError
from ai_digest.publishing import CommandResult, PublishError, PublishingConfig, SummaryPublisher
from ai_digest.storage import SummaryRepository


DEFAULT_SITE_ROOT = "https://yamopeng0918.github.io/AI-Summary/"
DEFAULT_GITHUB_REPOSITORY = "yamopeng0918/AI-Summary"
DEFAULT_WORKFLOW_NAME = "Deploy to GitHub Pages"
USER_AGENT = "AI-Digest-Publisher/1.0"
REQUEST_TIMEOUT_SECONDS = 15.0


def _run_command(command: Sequence[str], cwd: Path) -> CommandResult:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
        text=False,
        shell=False,
    )
    return CommandResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr.decode("utf-8", errors="surrogateescape"),
    )


def _request(url: str) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return getattr(response, "status", 200), response.read()


def _fetch_json(url: str) -> object:
    _status, payload = _request(url)
    return json.loads(payload.decode("utf-8"))


def _fetch_text(url: str) -> tuple[int, str]:
    status, payload = _request(url)
    return status, payload.decode("utf-8")


def _build_publisher() -> SummaryPublisher:
    repository_root = REPOSITORY_ROOT
    summary_root = repository_root / "data" / "summaries"

    def add_summary(url: str):
        return cli._workflow().run(url, cli._now())

    return SummaryPublisher(
        config=PublishingConfig(
            repository_root=repository_root,
            summary_root=summary_root,
            site_root=DEFAULT_SITE_ROOT,
            github_repository=DEFAULT_GITHUB_REPOSITORY,
            workflow_name=DEFAULT_WORKFLOW_NAME,
        ),
        repository=SummaryRepository(Path("data/summaries")),
        add_summary=add_summary,
        run_command=_run_command,
        fetch_json=_fetch_json,
        fetch_text=_fetch_text,
        sleep=time.sleep,
        now=lambda: int(time.time()),
    )


def _emit(payload: dict[str, object], *, err: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr if err else sys.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish one public article URL to AI Digest.")
    parser.add_argument("url")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    publisher = _build_publisher()
    try:
        result = publisher.publish(args.url)
    except PublishError as error:
        _emit({"stage": error.stage, "message": error.message}, err=True)
        return 1
    except DigestError as error:
        _emit(error.as_dict(), err=True)
        return 1

    _emit(
        {
            "id": result.record_id,
            "commit": result.commit_sha,
            "workflow": result.workflow_url,
            "detail": result.detail_url,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
