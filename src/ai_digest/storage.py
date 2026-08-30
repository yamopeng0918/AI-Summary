"""Atomic JSON persistence for validated summary records."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ai_digest.domain import DigestError, SummaryRecord


class SummaryRepository:
    """Store one validated summary record per JSON file."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, record: SummaryRecord) -> Path:
        """Atomically save a new record unless its canonical URL already exists."""
        destination = self._record_path(record.id)
        existing_records = self._load_all()
        if any(existing.id == record.id for existing in existing_records):
            raise DigestError("save", "DUPLICATE_ID", "A summary already exists for this ID", False)
        for existing in existing_records:
            if str(existing.canonical_url) == str(record.canonical_url):
                raise DigestError(
                    "save", "DUPLICATE_URL", "A summary already exists for this URL", False
                )
        self._write(destination, record)
        return destination

    def list(self) -> list[SummaryRecord]:
        """Return all stored records in stable ID order."""
        return sorted(self._load_all(), key=lambda record: record.id)

    def get(self, record_id: str) -> SummaryRecord:
        """Return one stored record by ID."""
        path = self._record_path(record_id)
        if not path.is_file():
            raise DigestError("save", "RECORD_NOT_FOUND", "Summary record was not found", False)
        return self._load_path(path)

    def replace(self, record_id: str, updated_record: SummaryRecord) -> Path:
        """Atomically replace one existing record after identity and URL checks."""
        self.get(record_id)
        if updated_record.id != record_id:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False)
        for existing in self._load_all():
            if existing.id != record_id and str(existing.canonical_url) == str(updated_record.canonical_url):
                raise DigestError("save", "DUPLICATE_URL", "A summary already exists for this URL", False)
        destination = self._record_path(record_id)
        self._write(destination, updated_record)
        return destination

    def set_status(
        self,
        record_id: str,
        status: Literal["published", "archived"],
        now: datetime,
    ) -> SummaryRecord:
        """Update just a record's publication status and update timestamp."""
        if status not in {"published", "archived"}:
            raise DigestError("save", "INVALID_STATUS", "Summary status is invalid", False)
        record = self.get(record_id)
        payload = record.model_dump(mode="json", by_alias=True)
        payload.update({"status": status, "updatedAt": now.isoformat()})
        try:
            updated = SummaryRecord.model_validate(payload)
        except ValidationError as error:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False) from error
        self._write(self._record_path(record_id), updated)
        return updated

    def _load_all(self) -> list[SummaryRecord]:
        if not self.root.exists():
            return []
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError as error:
            raise DigestError("save", "READ_FAILED", "Stored summaries could not be read", True) from error
        return [self._load_path(path) for path in paths]

    def _load_path(self, path: Path) -> SummaryRecord:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = SummaryRecord.model_validate(payload)
            if path.stem != record.id:
                raise ValueError("record ID does not match filename")
            return record
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise DigestError(
                "save", "INVALID_EXISTING_DATA", "Stored summary data is invalid", False
            ) from error

    def _record_path(self, record_id: str) -> Path:
        if not record_id or Path(record_id).name != record_id or record_id in {".", ".."}:
            raise DigestError("save", "INVALID_RECORD", "Summary record is invalid", False)
        return self.root / f"{record_id}.json"

    def _write(self, destination: Path, record: SummaryRecord) -> None:
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(record.model_dump(mode="json", by_alias=True), handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise DigestError("save", "WRITE_FAILED", "Summary record could not be saved", True) from error
