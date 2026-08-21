"""Offline loading and validation for classifier training data."""

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence, cast
from urllib.parse import urlsplit, urlunsplit

from ai_digest.domain import DigestError


_CSV_FIELDS = (
    "id",
    "batch",
    "text",
    "label",
    "sourceUrl",
    "sourceTitle",
    "rationale",
    "reviewStatus",
    "reviewNote",
)
_REVIEW_STATES = frozenset({"pending", "approved", "rejected"})


@dataclass(frozen=True, slots=True)
class TrainingExample:
    id: str
    batch: int
    text: str
    label: str
    source_url: str
    source_title: str
    rationale: str
    review_status: Literal["pending", "approved", "rejected"]
    review_note: str


def load_dataset(path: Path, categories: Sequence[str]) -> list[TrainingExample]:
    """Load and validate every UTF-8 CSV row without using the network."""
    try:
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != _CSV_FIELDS:
                raise ValueError("unexpected CSV header")
            examples = [_parse_row(row, categories) for row in reader]
        _reject_duplicates(examples)
        return examples
    except DigestError:
        raise
    except (csv.Error, OSError, UnicodeError, TypeError, ValueError) as error:
        raise _invalid_dataset() from error


def approved_cohort(
    examples: Sequence[TrainingExample],
    categories: Sequence[str],
    expected_per_category: int,
) -> list[TrainingExample]:
    """Return approved rows only after enforcing exact per-category counts."""
    configured = tuple(categories)
    configured_set = set(configured)
    observed_set = {example.label for example in examples}
    if not configured or len(configured) != len(configured_set) or observed_set != configured_set:
        raise _classifier_error("CATEGORY_MISMATCH", "Classifier categories do not match")
    if expected_per_category < 1:
        raise _invalid_dataset()

    approved = [example for example in examples if example.review_status == "approved"]
    counts = Counter(example.label for example in approved)
    if any(example.review_status == "pending" for example in examples):
        raise _classifier_error("UNAPPROVED_DATA", "Classifier data review is incomplete")
    if all(counts[category] == expected_per_category for category in configured):
        return approved
    if any(counts[category] < expected_per_category for category in configured):
        raise _classifier_error("INSUFFICIENT_SAMPLES", "Classifier dataset has insufficient samples")
    raise _invalid_dataset()


def dataset_sha256(examples: Sequence[TrainingExample]) -> str:
    """Return a stable content hash independent of input row order."""
    serialized_rows = [
        {
            "id": example.id,
            "batch": example.batch,
            "text": example.text,
            "label": example.label,
            "sourceUrl": example.source_url,
            "sourceTitle": example.source_title,
            "rationale": example.rationale,
            "reviewStatus": example.review_status,
            "reviewNote": example.review_note,
        }
        for example in sorted(
            (item for item in examples if item.review_status == "approved"),
            key=lambda item: item.id,
        )
    ]
    payload = json.dumps(serialized_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_row(row: dict[str | None, str | list[str] | None], categories: Sequence[str]) -> TrainingExample:
    if set(row) != set(_CSV_FIELDS) or any(not isinstance(row[field], str) for field in _CSV_FIELDS):
        raise ValueError("invalid CSV row")
    values = {field: cast(str, row[field]).strip() for field in _CSV_FIELDS}
    required = _CSV_FIELDS[:-1]
    if any(not values[field] for field in required):
        raise ValueError("blank required field")

    batch = int(values["batch"])
    if batch not in {1, 2, 3}:
        raise ValueError("invalid batch")
    if values["label"] not in categories:
        raise ValueError("unknown category")
    if values["reviewStatus"] not in _REVIEW_STATES:
        raise ValueError("invalid review state")
    _canonical_source_url(values["sourceUrl"])

    return TrainingExample(
        id=values["id"],
        batch=batch,
        text=values["text"],
        label=values["label"],
        source_url=values["sourceUrl"],
        source_title=values["sourceTitle"],
        rationale=values["rationale"],
        review_status=cast(Literal["pending", "approved", "rejected"], values["reviewStatus"]),
        review_note=values["reviewNote"],
    )


def _reject_duplicates(examples: Sequence[TrainingExample]) -> None:
    ids = [example.id for example in examples]
    urls = [_canonical_source_url(example.source_url) for example in examples]
    if len(ids) != len(set(ids)) or len(urls) != len(set(urls)):
        raise ValueError("duplicate dataset identity")


def _canonical_source_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid source URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("invalid source URL")
    port = parsed.port
    host = parsed.hostname.lower().rstrip(".")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1] or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _invalid_dataset() -> DigestError:
    return DigestError("classify", "INVALID_DATASET", "Classifier dataset is invalid", False)


def _classifier_error(code: str, message: str) -> DigestError:
    return DigestError("classify", code, message, False)
