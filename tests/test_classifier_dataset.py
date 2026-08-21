from pathlib import Path

import pytest

from dataclasses import FrozenInstanceError, replace

from ai_digest.classifiers.dataset import (
    TrainingExample,
    approved_cohort,
    dataset_sha256,
    load_dataset,
)
from ai_digest.domain import DigestError


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "classifier"
CATEGORIES = (
    "人工智慧",
    "程式開發",
    "科技產業",
    "商業與職場",
    "設計與創意",
    "生活與學習",
)


def test_load_dataset_parses_utf8_rows_in_file_order() -> None:
    rows = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)

    assert [row.id for row in rows] == [f"example-{index}" for index in range(1, 7)]
    assert [row.label for row in rows] == list(CATEGORIES)
    assert all(row.review_status == "approved" for row in rows)

    with pytest.raises(FrozenInstanceError):
        rows[0].text = "不可修改"  # type: ignore[misc]


HEADER = "id,batch,text,label,sourceUrl,sourceTitle,rationale,reviewStatus,reviewNote"
VALID_ROW = (
    "example-1,1,secret-row-marker,人工智慧,https://example.com/article,"
    "文章標題,分類理由,approved,"
)


def _write_csv(path: Path, header: str = HEADER, *rows: str) -> Path:
    path.write_text("\n".join((header, *(rows or (VALID_ROW,)))) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("header", "row"),
    [
        (HEADER.replace(",reviewNote", ""), VALID_ROW.rsplit(",", 1)[0]),
        (f"{HEADER},unexpected", f"{VALID_ROW},value"),
        (HEADER, VALID_ROW.replace("example-1", " ", 1)),
        (HEADER, VALID_ROW.replace(",1,", ",4,", 1)),
        (HEADER, VALID_ROW.replace(",approved,", ",reviewing,")),
        (HEADER, VALID_ROW.replace(",人工智慧,", ",未知分類,")),
        (HEADER, VALID_ROW.replace("https://example.com/article", "ftp://example.com/article")),
    ],
)
def test_load_dataset_rejects_invalid_rows_without_exposing_content(
    tmp_path: Path,
    header: str,
    row: str,
) -> None:
    path = _write_csv(tmp_path / "training.csv", header, row)

    with pytest.raises(DigestError) as raised:
        load_dataset(path, CATEGORIES)

    assert (raised.value.stage, raised.value.code) == ("classify", "INVALID_DATASET")
    assert "secret-row-marker" not in str(raised.value)


@pytest.mark.parametrize(
    "second_row",
    [
        VALID_ROW.replace("https://example.com/article", "https://example.com/other"),
        VALID_ROW.replace("example-1", "example-2", 1).replace(
            "https://example.com/article", "HTTPS://EXAMPLE.COM/article/#fragment"
        ),
    ],
)
def test_load_dataset_rejects_duplicate_ids_or_canonical_urls(
    tmp_path: Path,
    second_row: str,
) -> None:
    path = _write_csv(tmp_path / "training.csv", HEADER, VALID_ROW, second_row)

    with pytest.raises(DigestError) as raised:
        load_dataset(path, CATEGORIES)

    assert (raised.value.stage, raised.value.code) == ("classify", "INVALID_DATASET")
    assert "secret-row-marker" not in str(raised.value)


def test_load_dataset_preserves_query_and_repeated_trailing_slashes(tmp_path: Path) -> None:
    rows = (
        VALID_ROW,
        VALID_ROW.replace("example-1", "example-2", 1).replace(
            "https://example.com/article", "https://example.com/article//"
        ),
        VALID_ROW.replace("example-1", "example-3", 1).replace(
            "https://example.com/article", "https://example.com/article?view=full"
        ),
    )

    assert len(load_dataset(_write_csv(tmp_path / "training.csv", HEADER, *rows), CATEGORIES)) == 3


def _example(index: int, label: str, status: str = "approved") -> TrainingExample:
    return TrainingExample(
        id=f"cohort-{index}",
        batch=1,
        text=f"第 {index} 筆訓練內容",
        label=label,
        source_url=f"https://example.com/cohort/{index}",
        source_title=f"來源 {index}",
        rationale="分類明確",
        review_status=status,  # type: ignore[arg-type]
        review_note="",
    )


def test_approved_cohort_returns_only_approved_rows_in_input_order() -> None:
    approved = [_example(index, label) for index, label in enumerate(CATEGORIES, start=1)]
    history = replace(approved[1], id="rejected-history", review_status="rejected")

    result = approved_cohort([*approved, history], CATEGORIES, 1)

    assert result == approved


def test_approved_cohort_rejects_pending_history_after_counts_are_met() -> None:
    approved = [_example(index, label) for index, label in enumerate(CATEGORIES, start=1)]
    pending = replace(approved[0], id="pending-history", review_status="pending")

    with pytest.raises(DigestError) as raised:
        approved_cohort([*approved, pending], CATEGORIES, 1)

    assert (raised.value.stage, raised.value.code) == ("classify", "UNAPPROVED_DATA")


@pytest.mark.parametrize(
    ("examples", "categories", "expected_code"),
    [
        ([_example(1, CATEGORIES[0])], CATEGORIES[:-1], "CATEGORY_MISMATCH"),
        (
            [_example(index, label) for index, label in enumerate(CATEGORIES, start=1)][:-1],
            CATEGORIES,
            "CATEGORY_MISMATCH",
        ),
        (
            [
                *[_example(index, label) for index, label in enumerate(CATEGORIES, start=1)],
                _example(20, CATEGORIES[0], "pending"),
            ],
            CATEGORIES,
            "UNAPPROVED_DATA",
        ),
        (
            [_example(index, label) for index, label in enumerate(CATEGORIES, start=1)],
            CATEGORIES,
            "INSUFFICIENT_SAMPLES",
        ),
    ],
)
def test_approved_cohort_reports_safe_validation_errors(
    examples: list[TrainingExample],
    categories: tuple[str, ...],
    expected_code: str,
) -> None:
    with pytest.raises(DigestError) as raised:
        approved_cohort(examples, categories, 2)

    assert (raised.value.stage, raised.value.code) == ("classify", expected_code)
    assert "訓練內容" not in str(raised.value)


def test_dataset_sha256_is_independent_of_input_order() -> None:
    examples = [_example(1, CATEGORIES[0]), _example(2, CATEGORIES[1])]

    assert dataset_sha256(examples) == dataset_sha256(list(reversed(examples)))
    assert len(dataset_sha256(examples)) == 64


def test_dataset_sha256_ignores_non_approved_review_history() -> None:
    approved = [_example(1, CATEGORIES[0]), _example(2, CATEGORIES[1])]
    history = [
        _example(3, CATEGORIES[2], "pending"),
        _example(4, CATEGORIES[3], "rejected"),
    ]

    assert dataset_sha256(approved) == dataset_sha256([*approved, *history])


@pytest.mark.parametrize(
    "changed",
    [
        {"text": "不同的文章內容"},
        {"label": CATEGORIES[1]},
        {"source_url": "https://example.com/different"},
    ],
)
def test_dataset_sha256_changes_with_material_fields(changed: dict[str, str]) -> None:
    original = _example(1, CATEGORIES[0])

    assert dataset_sha256([original]) != dataset_sha256([replace(original, **changed)])
