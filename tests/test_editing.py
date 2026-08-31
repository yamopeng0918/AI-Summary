import subprocess
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest

from ai_digest.domain import DigestError, SummaryRecord, VALID_CATEGORIES
from ai_digest.editing import EditSummaryWorkflow, EditorRunner
from ai_digest.storage import SummaryRepository


CATEGORY = next(iter(VALID_CATEGORIES))
NOW = datetime(2026, 8, 31, 14, 30, tzinfo=timezone(timedelta(hours=8)))


def test_editor_runner_prefers_visual_and_never_uses_a_shell(tmp_path) -> None:
    calls: list[dict[str, object]] = []

    def run(args, *, check, shell):
        calls.append({"args": args, "check": check, "shell": shell})
        return subprocess.CompletedProcess(args, 0)

    editor = EditorRunner(
        {"VISUAL": "code --wait", "EDITOR": "ignored"},
        platform="win32",
        command_runner=run,
    )

    editor.edit(tmp_path / "record.json")

    assert calls == [
        {
            "args": ["code", "--wait", str(tmp_path / "record.json")],
            "check": False,
            "shell": False,
        }
    ]


@pytest.mark.parametrize(
    ("configured", "expected_command"),
    [
        (r"C:\Tools\editor.exe", [r"C:\Tools\editor.exe"]),
        (
            r'"C:\Program Files\Editor\editor.exe" --wait',
            [r"C:\Program Files\Editor\editor.exe", "--wait"],
        ),
    ],
)
def test_editor_runner_preserves_windows_executable_paths(
    configured, expected_command, tmp_path
) -> None:
    calls: list[dict[str, object]] = []

    def run(args, *, check, shell):
        calls.append({"args": args, "check": check, "shell": shell})
        return subprocess.CompletedProcess(args, 0)

    editor = EditorRunner({"VISUAL": configured}, platform="win32", command_runner=run)

    editor.edit(tmp_path / "record.json")

    assert calls == [
        {
            "args": [*expected_command, str(tmp_path / "record.json")],
            "check": False,
            "shell": False,
        }
    ]


def test_editor_runner_uses_editor_when_visual_is_blank(tmp_path) -> None:
    calls: list[list[str]] = []

    def run(args, *, check, shell):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    editor = EditorRunner(
        {"VISUAL": "  ", "EDITOR": "vim -f"},
        platform="linux",
        command_runner=run,
    )

    editor.edit(tmp_path / "record.json")

    assert calls == [["vim", "-f", str(tmp_path / "record.json")]]


def test_editor_runner_uses_notepad_on_windows_without_configuration(tmp_path) -> None:
    calls: list[list[str]] = []

    def run(args, *, check, shell):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    editor = EditorRunner({}, platform="win32", command_runner=run)

    editor.edit(tmp_path / "record.json")

    assert calls == [["notepad.exe", str(tmp_path / "record.json")]]


def test_editor_runner_rejects_missing_configuration_outside_windows(tmp_path) -> None:
    editor = EditorRunner(
        {},
        platform="linux",
        command_runner=lambda args, *, check, shell: subprocess.CompletedProcess(args, 0),
    )

    with pytest.raises(DigestError) as raised:
        editor.edit(tmp_path / "record.json")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "EDITOR_NOT_CONFIGURED",
        "message": "VISUAL or EDITOR must identify a text editor",
        "retryable": False,
    }


def test_editor_runner_reports_nonzero_exit_code(tmp_path) -> None:
    def run(args, *, check, shell):
        return subprocess.CompletedProcess(args, 1)

    editor = EditorRunner({"EDITOR": "vim"}, platform="linux", command_runner=run)

    with pytest.raises(DigestError) as raised:
        editor.edit(tmp_path / "record.json")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "EDITOR_FAILED",
        "message": "The text editor could not be run",
        "retryable": False,
    }


def test_editor_runner_reports_os_error(tmp_path) -> None:
    def run(args, *, check, shell):
        raise OSError("editor unavailable")

    editor = EditorRunner({"EDITOR": "vim"}, platform="linux", command_runner=run)

    with pytest.raises(DigestError) as raised:
        editor.edit(tmp_path / "record.json")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "EDITOR_FAILED",
        "message": "The text editor could not be run",
        "retryable": False,
    }


def test_editor_runner_reports_malformed_editor_command(tmp_path) -> None:
    calls: list[object] = []

    def run(args, *, check, shell):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    editor = EditorRunner(
        {"VISUAL": 'code "unterminated'}, platform="linux", command_runner=run
    )

    with pytest.raises(DigestError) as raised:
        editor.edit(tmp_path / "record.json")

    assert raised.value.as_dict() == {
        "stage": "input",
        "code": "EDITOR_FAILED",
        "message": "The text editor could not be run",
        "retryable": False,
    }
    assert calls == []


def make_record(record_id: str = "example") -> SummaryRecord:
    return SummaryRecord.model_validate(
        {
            "schemaVersion": 1,
            "id": record_id,
            "canonicalUrl": f"https://example.com/{record_id}",
            "sourceType": "web",
            "title": "Original title",
            "author": "Original author",
            "sourcePublishedAt": "2026-08-09T10:00:00+08:00",
            "createdAt": "2026-08-09T14:00:00+08:00",
            "updatedAt": "2026-08-09T14:00:00+08:00",
            "summary": "Original summary.",
            "keyPoints": ["One", "Two", "Three"],
            "category": CATEGORY,
            "tags": ["Original"],
            "editorial": "Original editorial.",
            "status": "published",
        }
    )


class JsonEditingFake:
    def __init__(self, change: Callable[[dict[str, object]], None]) -> None:
        self._change = change
        self.paths: list[Path] = []

    def edit(self, path: Path) -> None:
        self.paths.append(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._change(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")


def assert_temporary_files_removed(editor: JsonEditingFake) -> None:
    assert editor.paths
    assert all(not path.exists() for path in editor.paths)


@pytest.mark.parametrize(
    ("alias", "value"),
    [
        ("title", "Edited title"),
        ("author", "Edited author"),
        ("sourcePublishedAt", "2026-08-10T10:00:00+08:00"),
        ("summary", "Edited summary."),
        ("keyPoints", ["A", "B", "C"]),
        ("category", CATEGORY),
        ("tags", ["Edited"]),
        ("editorial", "Edited editorial."),
        ("status", "archived"),
    ],
)
def test_edit_workflow_allows_each_content_field(alias, value, tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__(alias, value))

    result = EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert result.model_dump(mode="json", by_alias=True)[alias] == value
    assert result.updated_at == NOW
    assert repository.get(original.id) == result
    assert_temporary_files_removed(editor)


@pytest.mark.parametrize(
    ("alias", "value"),
    [
        ("schemaVersion", 2),
        ("id", "changed"),
        ("canonicalUrl", "https://example.com/changed"),
        ("sourceType", "youtube"),
        ("createdAt", "2026-08-10T10:00:00+08:00"),
    ],
)
def test_edit_workflow_rejects_each_protected_field(alias, value, tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__(alias, value))

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.as_dict() == {
        "stage": "save",
        "code": "PROTECTED_FIELD_CHANGED",
        "message": "Protected summary fields cannot be changed",
        "retryable": False,
    }
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


@pytest.mark.parametrize("value", [True, 1.0])
def test_edit_workflow_rejects_type_changed_schema_version(value, tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__("schemaVersion", value))

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.as_dict() == {
        "stage": "save",
        "code": "PROTECTED_FIELD_CHANGED",
        "message": "Protected summary fields cannot be changed",
        "retryable": False,
    }
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


def test_edit_workflow_rejects_malformed_json_without_changing_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: None)

    def write_malformed_json(path: Path) -> None:
        editor.paths.append(path)
        path.write_text("{", encoding="utf-8")

    editor.edit = write_malformed_json  # type: ignore[method-assign]

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.as_dict() == {
        "stage": "save",
        "code": "INVALID_RECORD",
        "message": "Summary record is invalid",
        "retryable": False,
    }
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


def test_edit_workflow_rejects_invalid_utf8_without_changing_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: None)

    def write_invalid_utf8(path: Path) -> None:
        editor.paths.append(path)
        path.write_bytes(b"\xff")

    editor.edit = write_invalid_utf8  # type: ignore[method-assign]

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.code == "INVALID_RECORD"
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


def test_edit_workflow_rejects_schema_failure_without_changing_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__("summary", ""))

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.code == "INVALID_RECORD"
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


def test_edit_workflow_rejects_unexpected_json_alias_without_changing_record(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__("unexpected", "value"))

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.as_dict() == {
        "stage": "save",
        "code": "INVALID_RECORD",
        "message": "Summary record is invalid",
        "retryable": False,
    }
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


def test_edit_workflow_replaces_caller_supplied_updated_at(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(
        lambda payload: payload.update({"summary": "Edited summary.", "updatedAt": "2000-01-01T00:00:00+00:00"})
    )

    result = EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert result.summary == "Edited summary."
    assert result.updated_at == NOW
    assert repository.get(original.id).updated_at == NOW
    assert_temporary_files_removed(editor)


def test_edit_workflow_succeeds_without_content_changes(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: None)

    result = EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert result.model_dump(exclude={"updated_at"}) == original.model_dump(exclude={"updated_at"})
    assert result.updated_at == NOW
    assert repository.get(original.id) == result
    assert_temporary_files_removed(editor)


def test_edit_workflow_preserves_record_when_repository_write_fails(tmp_path, monkeypatch) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__("summary", "Edited summary."))

    def fail_replace(record_id: str, updated: SummaryRecord) -> Path:
        raise DigestError("save", "WRITE_FAILED", "Summary record could not be saved", True)

    monkeypatch.setattr(repository, "replace", fail_replace)

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.code == "WRITE_FAILED"
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)


def test_edit_workflow_does_not_replace_when_temporary_file_cannot_be_removed(
    tmp_path, monkeypatch
) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: payload.__setitem__("summary", "Edited summary."))
    original_unlink = Path.unlink
    unlink_calls: list[Path] = []

    def fail_temporary_unlink(self: Path, *, missing_ok: bool = False) -> None:
        if self in editor.paths:
            unlink_calls.append(self)
            raise OSError("temporary file is locked")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)

    try:
        with pytest.raises(DigestError) as raised:
            EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

        assert raised.value.as_dict() == {
            "stage": "save",
            "code": "WRITE_FAILED",
            "message": "Summary record could not be saved",
            "retryable": True,
        }
        assert repository.get(original.id) == original
        assert unlink_calls == editor.paths
    finally:
        for path in editor.paths:
            original_unlink(path, missing_ok=True)


def test_edit_workflow_cleans_temporary_file_when_editor_fails(tmp_path) -> None:
    repository = SummaryRepository(tmp_path / "summaries")
    original = make_record()
    repository.save(original)
    editor = JsonEditingFake(lambda payload: None)

    def fail_editor(path: Path) -> None:
        editor.paths.append(path)
        raise DigestError("input", "EDITOR_FAILED", "The text editor could not be run", False)

    editor.edit = fail_editor  # type: ignore[method-assign]

    with pytest.raises(DigestError) as raised:
        EditSummaryWorkflow(repository, editor, lambda: NOW).run(original.id)

    assert raised.value.code == "EDITOR_FAILED"
    assert repository.get(original.id) == original
    assert_temporary_files_removed(editor)
