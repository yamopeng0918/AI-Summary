"""Validated classifier training data."""

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence, cast
from urllib.parse import urlsplit, urlunsplit

from ai_digest.domain import DigestError


_CSV_HEADERS = (
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
_REQUIRED_HEADERS = _CSV_HEADERS[:-1]
_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected"})


def _invalid_dataset() -> DigestError:
    return DigestError("classify", "INVALID_DATASET", "Classifier dataset is invalid", False)


def _cohort_error(code: str, message: str) -> DigestError:
    return DigestError("classify", code, message, False)


def _canonical_source_url(source_url: str) -> str:
    """Return the duplicate-comparison key for one syntactically valid source URL."""
    parsed = urlsplit(source_url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("source URL is not HTTP(S)")

    port = parsed.port
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


@dataclass(frozen=True, slots=True)
class TrainingExample:
    """One reviewed classifier training row."""

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
    category_set = set(categories)
    examples: list[TrainingExample] = []
    seen_ids: set[str] = set()
    seen_source_urls: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as dataset_file:
            reader = csv.DictReader(dataset_file)
            if reader.fieldnames != list(_CSV_HEADERS):
                raise ValueError("CSV headers do not match")

            for row in reader:
                if None in row:
                    raise ValueError("CSV row has extra values")
                normalized = {key: (value or "").strip() for key, value in row.items()}
                if any(not normalized[field] for field in _REQUIRED_HEADERS):
                    raise ValueError("CSV row has blank required values")

                batch = int(normalized["batch"])
                review_status = normalized["reviewStatus"]
                source_url = normalized["sourceUrl"]
                if batch not in {1, 2, 3}:
                    raise ValueError("batch is outside the review range")
                if review_status not in _REVIEW_STATUSES:
                    raise ValueError("review status is invalid")
                if normalized["label"] not in category_set:
                    raise ValueError("label is not configured")
                canonical_source_url = _canonical_source_url(source_url)
                if normalized["id"] in seen_ids or canonical_source_url in seen_source_urls:
                    raise ValueError("dataset has duplicate identity")

                seen_ids.add(normalized["id"])
                seen_source_urls.add(canonical_source_url)
                examples.append(
                    TrainingExample(
                        id=normalized["id"],
                        batch=batch,
                        text=normalized["text"],
                        label=normalized["label"],
                        source_url=source_url,
                        source_title=normalized["sourceTitle"],
                        rationale=normalized["rationale"],
                        review_status=cast(Literal["pending", "approved", "rejected"], review_status),
                        review_note=normalized["reviewNote"],
                    )
                )
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as error:
        raise _invalid_dataset() from error

    return examples


def approved_cohort(
    examples: Sequence[TrainingExample],
    categories: Sequence[str],
    expected_per_category: int,
) -> list[TrainingExample]:
    """Return approved rows only after enforcing exact per-category counts."""
    category_set = set(categories)
    example_category_set = {example.label for example in examples}
    if len(category_set) != len(categories) or category_set != example_category_set:
        raise _cohort_error("CATEGORY_MISMATCH", "Classifier categories do not match the dataset")
    if any(example.review_status == "pending" for example in examples):
        raise _cohort_error("UNAPPROVED_DATA", "Classifier dataset has unapproved rows")

    approved = [example for example in examples if example.review_status == "approved"]
    for category in categories:
        count = sum(example.label == category for example in approved)
        if count < expected_per_category:
            raise _cohort_error("INSUFFICIENT_SAMPLES", "Classifier dataset has insufficient samples")
        if count > expected_per_category:
            raise _cohort_error("UNAPPROVED_DATA", "Classifier dataset is not ready for final evaluation")
    return approved


def dataset_sha256(examples: Sequence[TrainingExample]) -> str:
    """Return a stable content hash for approved examples."""
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
            (example for example in examples if example.review_status == "approved"),
            key=lambda example: example.id,
        )
    ]
    payload = json.dumps(serialized_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
