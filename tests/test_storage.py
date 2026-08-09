import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_digest.domain import DigestError, SummaryRecord
from ai_digest import storage
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


def test_save_rejects_an_occupied_id_without_overwriting_existing_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    original = make_record("shared", status="archived")
    repository.save(original)

    with pytest.raises(DigestError) as raised:
        repository.save(make_record("shared", canonicalUrl="https://example.com/replacement"))

    assert raised.value.code == "DUPLICATE_ID"
    assert repository.get("shared") == original


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


def test_production_records_round_trip_from_list_to_get() -> None:
    repository = SummaryRepository(Path(__file__).parents[1] / "data" / "summaries")

    records = repository.list()

    assert records
    assert [repository.get(record.id) for record in records] == records


def test_list_rejects_filename_that_does_not_match_record_id(tmp_path) -> None:
    record = make_record("inside")
    (tmp_path / "outside.json").write_text(
        record.model_dump_json(by_alias=True), encoding="utf-8"
    )

    with pytest.raises(DigestError) as raised:
        SummaryRepository(tmp_path).list()

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "INVALID_EXISTING_DATA",
        False,
    )


def test_get_rejects_invalid_existing_json(tmp_path) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(DigestError) as raised:
        SummaryRepository(tmp_path).list()

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "INVALID_EXISTING_DATA",
        False,
    )


@pytest.mark.parametrize("operation", ["list", "get"])
def test_repository_rejects_invalid_utf8(operation: str, tmp_path) -> None:
    (tmp_path / "broken.json").write_bytes(b"\xff")
    repository = SummaryRepository(tmp_path)

    with pytest.raises(DigestError) as raised:
        getattr(repository, operation)(*("broken",) if operation == "get" else ())

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "INVALID_EXISTING_DATA",
        False,
    )


def test_get_rejects_a_missing_record(tmp_path) -> None:
    with pytest.raises(DigestError) as raised:
        SummaryRepository(tmp_path).get("missing")

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "RECORD_NOT_FOUND",
        False,
    )


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


def test_set_status_rejects_invalid_status(tmp_path) -> None:
    repository = SummaryRepository(tmp_path)
    repository.save(make_record("example"))

    with pytest.raises(DigestError) as raised:
        repository.set_status("example", "draft", datetime.now().astimezone())  # type: ignore[arg-type]

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "INVALID_STATUS",
        False,
    )


def test_save_reports_write_failure(tmp_path, monkeypatch) -> None:
    repository = SummaryRepository(tmp_path)

    def fail_replace(source, destination) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(storage.os, "replace", fail_replace)

    with pytest.raises(DigestError) as raised:
        repository.save(make_record())

    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "save",
        "WRITE_FAILED",
        True,
    )
    assert not list(tmp_path.glob("*.tmp"))
