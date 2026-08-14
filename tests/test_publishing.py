from pathlib import Path

import pytest

from ai_digest.publishing import CommandResult, PublishError, PublishingConfig, SummaryPublisher
from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES


REPOSITORY_ROOT = Path("C:/workspace/AI-Summary")
SUMMARY_ROOT = REPOSITORY_ROOT / "data" / "summaries"
CATEGORY = next(iter(VALID_CATEGORIES))


class FakeRepository:
    def __init__(self, records: list[SummaryRecord]) -> None:
        self._records = records

    def list(self) -> list[SummaryRecord]:
        return list(self._records)


class RecordingRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> CommandResult:
        self.calls.append((command, cwd))
        return self.responses.pop(0)


def result(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)


def make_record(record_id: str = "example", **changes: object) -> SummaryRecord:
    payload = {
        "schemaVersion": 1,
        "id": record_id,
        "canonicalUrl": f"https://example.com/{record_id}",
        "sourceType": "web",
        "title": "Example title",
        "author": None,
        "sourcePublishedAt": None,
        "createdAt": "2026-08-09T14:00:00+08:00",
        "updatedAt": "2026-08-09T14:00:00+08:00",
        "summary": "An example summary.",
        "keyPoints": ["First point", "Second point", "Third point"],
        "category": CATEGORY,
        "tags": ["AI"],
        "editorial": "Editorial note.",
        "status": "published",
    }
    payload.update(changes)
    return SummaryRecord.model_validate(payload)


def make_publisher(
    runner: RecordingRunner,
    *,
    repository: object | None = None,
    add_summary=None,
    summary_root: Path = SUMMARY_ROOT,
) -> SummaryPublisher:
    config = PublishingConfig(
        repository_root=REPOSITORY_ROOT,
        summary_root=summary_root,
        site_root="https://yamopeng0918.github.io/AI-Summary/",
        github_repository="yamopeng0918/AI-Summary",
        workflow_name="Deploy to GitHub Pages",
    )
    return SummaryPublisher(
        config=config,
        repository=repository if repository is not None else object(),
        add_summary=add_summary or (lambda _url: None),
        run_command=runner,
        fetch_json=lambda _url: {},
        fetch_text=lambda _url: (200, ""),
        sleep=lambda _seconds: None,
        now=lambda: 0,
    )


def expected_commands() -> list[list[str]]:
    return [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "branch", "--show-current"],
        ["git", "status", "--porcelain", "--untracked-files=no"],
        ["git", "fetch", "origin", "master"],
        ["git", "rev-list", "--left-right", "--count", "master...origin/master"],
    ]


def test_preflight_checks_clean_master_repository_in_order() -> None:
    runner = RecordingRunner(
        [
            result(str(REPOSITORY_ROOT)),
            result("master\n"),
            result(),
            result(),
            result("0\t0\n"),
        ]
    )

    make_publisher(runner).preflight()

    assert [command for command, _ in runner.calls] == expected_commands()
    assert [cwd for _, cwd in runner.calls] == [REPOSITORY_ROOT] * 5


@pytest.mark.parametrize(
    ("responses", "expected_call_count"),
    [
        ([result("C:/another/repository\n")], 1),
        ([result(str(REPOSITORY_ROOT)), result("feature/publish\n")], 2),
        (
            [
                result(str(REPOSITORY_ROOT)),
                result("master\n"),
                result(" M tracked-file.py\n"),
            ],
            3,
        ),
        (
            [
                result(str(REPOSITORY_ROOT)),
                result("master\n"),
                result(),
                result(),
                result("1\t0\n"),
            ],
            5,
        ),
    ],
    ids=["wrong-root", "wrong-branch", "dirty-tracked-files", "remote-diverged"],
)
def test_preflight_stops_at_the_first_invalid_git_state(
    responses: list[CommandResult], expected_call_count: int
) -> None:
    runner = RecordingRunner(responses)

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).preflight()

    assert raised.value.stage == "preflight"
    assert len(runner.calls) == expected_call_count
    assert [command for command, _ in runner.calls] == expected_commands()[:expected_call_count]


def test_preflight_maps_git_command_failures_to_sanitized_error() -> None:
    runner = RecordingRunner([result(returncode=128, stderr="fatal: unsafe details\nnext line")])

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).preflight()

    assert raised.value.stage == "preflight"
    assert raised.value.message == "git command failed"


def test_preflight_does_not_leak_credentials_from_git_stderr() -> None:
    leaked_token = "ghp_superSecretToken123"
    leaked_url = f"https://oauth2:{leaked_token}@github.com/yamopeng0918/AI-Summary.git"
    runner = RecordingRunner([result(returncode=128, stderr=f"fatal: could not read from {leaked_url}\n")])

    with pytest.raises(PublishError) as raised:
        make_publisher(runner).preflight()

    assert raised.value.stage == "preflight"
    assert raised.value.message == "git command failed"
    assert leaked_token not in raised.value.message
    assert leaked_url not in raised.value.message


def test_resolve_summary_creates_a_new_summary_when_no_canonical_match_exists(tmp_path) -> None:
    created = make_record("created", canonicalUrl="https://example.com/article")
    add_calls: list[str] = []

    record, path, created_new = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([]),
        add_summary=lambda raw_url: add_calls.append(raw_url) or created,
        summary_root=tmp_path,
    ).resolve_summary("https://example.com/article?utm_source=newsletter")

    assert record == created
    assert path == tmp_path / "created.json"
    assert created_new is True
    assert add_calls == ["https://example.com/article?utm_source=newsletter"]


def test_resolve_summary_reuses_an_existing_canonical_match_without_calling_provider(tmp_path) -> None:
    existing = make_record("existing", canonicalUrl="https://example.com/article")
    existing_path = tmp_path / "existing.json"
    existing_path.write_text(existing.model_dump_json(by_alias=True), encoding="utf-8")
    add_calls: list[str] = []

    record, path, created_new = make_publisher(
        RecordingRunner([]),
        repository=FakeRepository([existing]),
        add_summary=lambda raw_url: add_calls.append(raw_url) or make_record("unexpected"),
        summary_root=tmp_path,
    ).resolve_summary("https://example.com/article?utm_source=newsletter")

    assert record == existing
    assert path == existing_path
    assert created_new is False
    assert add_calls == []


def test_resolve_summary_rejects_multiple_existing_canonical_matches(tmp_path) -> None:
    first = make_record("first", canonicalUrl="https://example.com/article")
    second = make_record("second", canonicalUrl="https://example.com/article")

    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([first, second]),
            summary_root=tmp_path,
        ).resolve_summary("https://example.com/article")

    assert raised.value.stage == "summary"
    assert raised.value.message == "multiple summaries already exist for this URL"


def test_resolve_summary_rejects_a_retained_match_when_its_file_is_missing(tmp_path) -> None:
    existing = make_record("existing", canonicalUrl="https://example.com/article")

    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([existing]),
            summary_root=tmp_path,
        ).resolve_summary("https://example.com/article")

    assert raised.value.stage == "summary"
    assert raised.value.message == "stored summary file is missing"


def test_resolve_summary_maps_invalid_public_urls_to_a_safe_publishing_error(tmp_path) -> None:
    with pytest.raises(PublishError) as raised:
        make_publisher(
            RecordingRunner([]),
            repository=FakeRepository([]),
            summary_root=tmp_path,
        ).resolve_summary("file:///private")

    assert raised.value.stage == "summary"
    assert raised.value.message == "URL must be a public HTTP(S) URL"
