import json
from datetime import datetime, timedelta

import pytest

from ai_digest.domain import DigestError, SummaryRecord
from ai_digest.storage import SummaryRepository


def make_record(record_id: str = "second", **changes: object) -> SummaryRecord:
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
        "category": "人工智慧",
        "tags": ["AI"],
        "editorial": "Editorial note.",
        "status": "published",
    }
    payload.update(changes)
    return SummaryRecord.model_validate(payload)


def test_save_writes_alias_json_and_removes_temporary_file(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    record = make_record()

    path = repository.save(record)

    assert path == tmp_path / "second.json"
    assert json.loads(path.read_text(encoding="utf-8"))["canonicalUrl"] == str(record.canonical_url)
    assert not list(tmp_path.glob("*.tmp"))


def test_save_rejects_duplicate_canonical_url(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    repository.save(make_record("first", canonicalUrl="https://example.com/shared"))

    with pytest.raises(DigestError) as raised:
        repository.save(make_record("second", canonicalUrl="https://example.com/shared"))

    error = raised.value
    assert (error.stage, error.code, error.retryable) == ("save", "DUPLICATE_URL", False)


def test_list_returns_records_sorted_by_id(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    repository.save(make_record("zeta"))
    repository.save(make_record("alpha"))

    assert [record.id for record in repository.list()] == ["alpha", "zeta"]


def test_get_returns_saved_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    saved = make_record("example")
    repository.save(saved)

    assert repository.get("example") == saved


def test_set_status_changes_only_status_and_updated_at(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    saved = make_record("example")
    repository.save(saved)
    now = saved.updated_at + timedelta(minutes=1)

    updated = repository.set_status("example", "archived", now)

    assert updated.status == "archived"
    assert updated.updated_at == now
    assert updated.model_dump(exclude={"status", "updated_at"}) == saved.model_dump(
        exclude={"status", "updated_at"}
    )
