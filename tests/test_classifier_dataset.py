import json
import csv
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Iterable

import pytest

from ai_digest.classifiers.dataset import (
    TrainingExample,
    approved_cohort,
    dataset_sha256,
    load_dataset,
)
from ai_digest.domain import DigestError


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "classifier"
CATEGORIES = tuple(
    json.loads((Path(__file__).parents[1] / "data" / "categories.json").read_text(encoding="utf-8"))
)
CSV_HEADERS = (
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


def valid_row(**changes: str) -> dict[str, str]:
    row = {
        "id": "valid-example",
        "batch": "1",
        "text": "secret-row-marker",
        "label": CATEGORIES[0],
        "sourceUrl": "https://example.com/article",
        "sourceTitle": "來源標題",
        "rationale": "分類依據",
        "reviewStatus": "approved",
        "reviewNote": "",
    }
    row.update(changes)
    return row


def write_dataset(
    path: Path,
    rows: Iterable[dict[str, str]],
    headers: tuple[str, ...] = CSV_HEADERS,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as dataset_file:
        writer = csv.DictWriter(dataset_file, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def assert_invalid_dataset(path: Path) -> None:
    with pytest.raises(DigestError) as raised:
        load_dataset(path, CATEGORIES)

    assert (raised.value.stage, raised.value.code) == ("classify", "INVALID_DATASET")
    assert "secret-row-marker" not in str(raised.value)


def test_load_dataset_parses_utf8_rows_in_file_order() -> None:
    rows = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)

    assert [row.id for row in rows] == [f"example-{index}" for index in range(1, 7)]
    assert [row.label for row in rows] == list(CATEGORIES)
    assert all(row.review_status == "approved" for row in rows)
    assert rows[0].text == "人工智慧模型的應用"
    assert rows[0].source_url == "https://example.com/ai"
    assert rows[0].source_title == "AI 文章"


def test_training_example_is_immutable() -> None:
    example = TrainingExample(
        id="example-1",
        batch=1,
        text="分類文字",
        label=CATEGORIES[0],
        source_url="https://example.com/article",
        source_title="文章",
        rationale="理由",
        review_status="approved",
        review_note="",
    )

    with pytest.raises(FrozenInstanceError):
        example.text = "修改後的文字"  # type: ignore[misc]


@pytest.mark.parametrize(
    "headers",
    (
        CSV_HEADERS[:-1],
        (*CSV_HEADERS, "unexpected"),
    ),
)
def test_load_dataset_rejects_non_exact_headers(tmp_path: Path, headers: tuple[str, ...]) -> None:
    path = tmp_path / "invalid.csv"
    write_dataset(path, [valid_row()], headers)

    assert_invalid_dataset(path)


@pytest.mark.parametrize(
    "field",
    ("id", "batch", "text", "label", "sourceUrl", "sourceTitle", "rationale", "reviewStatus"),
)
def test_load_dataset_rejects_blank_required_fields(tmp_path: Path, field: str) -> None:
    path = tmp_path / "invalid.csv"
    write_dataset(path, [valid_row(**{field: "   "})])

    assert_invalid_dataset(path)


@pytest.mark.parametrize(
    "changes",
    (
        {"batch": "4"},
        {"reviewStatus": "reviewing"},
        {"label": "unknown-category"},
        {"sourceUrl": "ftp://example.com/article"},
    ),
)
def test_load_dataset_rejects_invalid_field_values(tmp_path: Path, changes: dict[str, str]) -> None:
    path = tmp_path / "invalid.csv"
    write_dataset(path, [valid_row(**changes)])

    assert_invalid_dataset(path)


def test_load_dataset_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    write_dataset(path, [valid_row(), valid_row(sourceUrl="https://example.com/other")])

    assert_invalid_dataset(path)


def test_load_dataset_rejects_duplicate_canonical_source_urls(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    write_dataset(
        path,
        [
            valid_row(sourceUrl="https://EXAMPLE.com/topic/#first"),
            valid_row(id="second-example", sourceUrl="https://example.com/topic#second"),
        ],
    )

    assert_invalid_dataset(path)


def test_approved_cohort_returns_approved_rows_in_file_order_after_exact_count_validation() -> None:
    examples = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)

    cohort = approved_cohort(examples, CATEGORIES, expected_per_category=1)

    assert cohort == examples


def test_approved_cohort_rejects_pending_rows_before_final_evaluation() -> None:
    examples = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)
    examples[0] = replace(examples[0], review_status="pending")

    with pytest.raises(DigestError) as raised:
        approved_cohort(examples, CATEGORIES, expected_per_category=1)

    assert (raised.value.stage, raised.value.code) == ("classify", "UNAPPROVED_DATA")


def test_approved_cohort_rejects_category_set_disagreement() -> None:
    examples = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)

    with pytest.raises(DigestError) as raised:
        approved_cohort(examples, CATEGORIES[:-1], expected_per_category=1)

    assert (raised.value.stage, raised.value.code) == ("classify", "CATEGORY_MISMATCH")


def test_approved_cohort_rejects_insufficient_approved_examples() -> None:
    examples = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)

    with pytest.raises(DigestError) as raised:
        approved_cohort(examples, CATEGORIES, expected_per_category=2)

    assert (raised.value.stage, raised.value.code) == ("classify", "INSUFFICIENT_SAMPLES")


def test_approved_cohort_rejects_more_than_the_expected_per_category() -> None:
    examples = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)
    examples.append(
        replace(
            examples[0],
            id="additional-example",
            source_url="https://example.com/additional",
        )
    )

    with pytest.raises(DigestError) as raised:
        approved_cohort(examples, CATEGORIES, expected_per_category=1)

    assert (raised.value.stage, raised.value.code) == ("classify", "UNAPPROVED_DATA")


def test_dataset_sha256_is_order_independent_and_changes_with_content() -> None:
    examples = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)

    original_hash = dataset_sha256(examples)

    assert original_hash == dataset_sha256(list(reversed(examples)))
    assert len(original_hash) == 64
    assert original_hash != dataset_sha256([replace(examples[0], text="changed"), *examples[1:]])
    assert original_hash != dataset_sha256([replace(examples[0], label=CATEGORIES[1]), *examples[1:]])
    assert original_hash != dataset_sha256(
        [replace(examples[0], source_url="https://example.com/changed"), *examples[1:]]
    )
