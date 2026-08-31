"""Safe local editing boundaries for stored summaries."""

from __future__ import annotations

import shlex
import subprocess
import json
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ai_digest.domain import DigestError, SummaryRecord
from ai_digest.storage import SummaryRepository


_PROTECTED_ALIASES = ("schemaVersion", "id", "canonicalUrl", "sourceType", "createdAt")


class EditorRunner:
    """Run a configured text editor without a shell."""

    def __init__(
        self,
        environment: Mapping[str, str],
        *,
        platform: str,
        command_runner: Callable[..., subprocess.CompletedProcess[object]],
    ) -> None:
        self._environment = environment
        self._platform = platform
        self._command_runner = command_runner

    def edit(self, path: Path) -> None:
        """Open ``path`` in the configured editor and wait for it to exit."""
        configured = next(
            (
                value.strip()
                for name in ("VISUAL", "EDITOR")
                if (value := self._environment.get(name, "")).strip()
            ),
            None,
        )
        try:
            if configured is not None:
                command = shlex.split(configured, posix=self._platform != "win32")
                if self._platform == "win32":
                    command = [
                        token[1:-1]
                        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}
                        else token
                        for token in command
                    ]
                if not command:
                    raise ValueError("empty editor command")
            elif self._platform == "win32":
                command = ["notepad.exe"]
            else:
                raise DigestError(
                    "input",
                    "EDITOR_NOT_CONFIGURED",
                    "VISUAL or EDITOR must identify a text editor",
                    False,
                )
            result = self._command_runner([*command, str(path)], check=False, shell=False)
        except DigestError:
            raise
        except (OSError, ValueError) as error:
            raise DigestError(
                "input", "EDITOR_FAILED", "The text editor could not be run", False
            ) from error
        if result.returncode != 0:
            raise DigestError(
                "input", "EDITOR_FAILED", "The text editor could not be run", False
            )


class EditSummaryWorkflow:
    """Edit one stored summary through a temporary JSON file."""

    def __init__(
        self,
        repository: SummaryRepository,
        editor: EditorRunner,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._editor = editor
        self._clock = clock

    def run(self, record_id: str) -> SummaryRecord:
        """Edit a record while preserving immutable source identity fields."""
        original = self._repository.get(record_id)
        original_payload = original.model_dump(mode="json", by_alias=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", delete=False
            ) as handle:
                json.dump(original_payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                temporary_path = Path(handle.name)
            self._editor.edit(temporary_path)
            edited_payload = json.loads(temporary_path.read_text(encoding="utf-8"))
            if not isinstance(edited_payload, dict):
                raise ValueError("summary record must be a JSON object")
            if set(edited_payload) != set(original_payload):
                raise ValueError("summary record fields do not match")
            for alias in _PROTECTED_ALIASES:
                edited_value = edited_payload.get(alias)
                original_value = original_payload[alias]
                if type(edited_value) is not type(original_value) or edited_value != original_value:
                    raise DigestError(
                        "save",
                        "PROTECTED_FIELD_CHANGED",
                        "Protected summary fields cannot be changed",
                        False,
                    )
            edited_payload["updatedAt"] = self._clock().isoformat()
            updated = SummaryRecord.model_validate(edited_payload)
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as error:
                temporary_path = None
                raise DigestError(
                    "save", "WRITE_FAILED", "Summary record could not be saved", True
                ) from error
            temporary_path = None
            self._repository.replace(record_id, updated)
            return updated
        except DigestError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
