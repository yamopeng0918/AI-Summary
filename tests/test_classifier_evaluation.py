import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_digest.classifiers import evaluation
from ai_digest.classifiers.dataset import TrainingExample
from ai_digest.classifiers.evaluation import create_split
from ai_digest.domain import DigestError


CATEGORIES = tuple(
    json.loads((Path(__file__).parents[1] / "data" / "categories.json").read_text(encoding="utf-8"))
)


def example(category: str, index: int) -> TrainingExample:
    return TrainingExample(
        id=f"{category}-{index:02}",
        batch=1,
        text=f"{category} 分類文字 {index}",
        label=category,
        source_url=f"https://example.com/{index}/{category}",
        source_title="來源標題",
        rationale="分類依據",
        review_status="approved",
        review_note="",
    )


def test_create_split_is_stratified_and_order_independent() -> None:
    examples = [example(category, index) for category in CATEGORIES for index in range(10)]

    first = create_split(examples, CATEGORIES, seed=42, test_per_category=2)
    second = create_split(list(reversed(examples)), CATEGORIES, seed=42, test_per_category=2)

    assert first == second
    assert set(first.train_ids).isdisjoint(first.test_ids)
    assert len(first.train_ids) == 48
    assert len(first.test_ids) == 12
    assert set(first.train_ids) | set(first.test_ids) == {example.id for example in examples}
    for category in CATEGORIES:
        assert sum(identifier.startswith(f"{category}-") for identifier in first.train_ids) == 8
        assert sum(identifier.startswith(f"{category}-") for identifier in first.test_ids) == 2


class FixedPredictions:
    def fit(self, texts: list[str], labels: list[str]) -> "FixedPredictions":
        return self

    def predict(self, texts: list[str]) -> list[str]:
        return [
            CATEGORIES[0]
            if CATEGORIES[-1] in text
            else next(category for category in CATEGORIES if category in text)
            for text in texts
        ]


def test_evaluate_split_calculates_reproducible_metrics_in_category_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    examples = [example(category, index) for category in CATEGORIES for index in range(2)]
    split = create_split(examples, CATEGORIES, seed=42, test_per_category=1)
    monkeypatch.setattr(evaluation, "build_pipeline", FixedPredictions)

    result = evaluation.evaluate_split(
        examples,
        split,
        CATEGORIES,
        evaluated_at=datetime(2026, 8, 18, 12, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    metrics = {metric.category: metric for metric in result.category_metrics}
    expected_matrix = (
        (1, 0, 0, 0, 0, 0),
        (0, 1, 0, 0, 0, 0),
        (0, 0, 1, 0, 0, 0),
        (0, 0, 0, 1, 0, 0),
        (0, 0, 0, 0, 1, 0),
        (1, 0, 0, 0, 0, 0),
    )

    assert result.accuracy == pytest.approx(5 / 6)
    assert result.macro_f1 == pytest.approx(7 / 9)
    assert result.majority_baseline_accuracy == pytest.approx(1 / 6)
    assert result.beats_baseline is True
    assert result.confusion_matrix == expected_matrix
    assert result.evaluated_at == "2026-08-18T12:00:00+08:00"
    assert (
        metrics[CATEGORIES[0]].precision,
        metrics[CATEGORIES[0]].recall,
        metrics[CATEGORIES[0]].f1,
        metrics[CATEGORIES[0]].support,
    ) == pytest.approx((0.5, 1.0, 2 / 3, 1))
    for category in CATEGORIES[1:-1]:
        assert (
            metrics[category].precision,
            metrics[category].recall,
            metrics[category].f1,
            metrics[category].support,
        ) == pytest.approx((1.0, 1.0, 1.0, 1))
    assert (
        metrics[CATEGORIES[-1]].precision,
        metrics[CATEGORIES[-1]].recall,
        metrics[CATEGORIES[-1]].f1,
        metrics[CATEGORIES[-1]].support,
    ) == (0.0, 0.0, 0.0, 1)
    assert result.as_dict()["evaluatedAt"] == "2026-08-18T12:00:00+08:00"


def test_build_pipeline_uses_the_approved_tfidf_and_logistic_regression_settings() -> None:
    pipeline = evaluation.build_pipeline()

    assert tuple(pipeline.named_steps) == ("tfidf", "classifier")
    assert pipeline.named_steps["tfidf"].analyzer == "char_wb"
    assert pipeline.named_steps["tfidf"].ngram_range == (2, 5)
    assert pipeline.named_steps["classifier"].max_iter == 2000
    assert pipeline.named_steps["classifier"].random_state == 42


@pytest.mark.parametrize(
    "examples",
    (
        [example(CATEGORIES[0], 0), example(CATEGORIES[0], 0)],
        [
            TrainingExample(
                id="",
                batch=1,
                text="分類文字",
                label=CATEGORIES[0],
                source_url="https://example.com/missing-id",
                source_title="來源標題",
                rationale="分類依據",
                review_status="approved",
                review_note="",
            )
        ],
        [
            TrainingExample(
                id="foreign",
                batch=1,
                text="分類文字",
                label="foreign-category",
                source_url="https://example.com/foreign",
                source_title="來源標題",
                rationale="分類依據",
                review_status="approved",
                review_note="",
            )
        ],
    ),
)
def test_create_split_rejects_missing_duplicate_or_foreign_examples(
    examples: list[TrainingExample],
) -> None:
    with pytest.raises(DigestError) as raised:
        create_split(examples, CATEGORIES, seed=42, test_per_category=1)

    assert (raised.value.stage, raised.value.code) == ("classify", "INVALID_DATASET")


class MajorityPredictions(FixedPredictions):
    def predict(self, texts: list[str]) -> list[str]:
        return [CATEGORIES[0] for _ in texts]


def test_evaluate_split_requires_accuracy_to_strictly_beat_the_majority_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    examples = [example(category, index) for category in CATEGORIES for index in range(2)]
    split = create_split(examples, CATEGORIES, seed=42, test_per_category=1)
    monkeypatch.setattr(evaluation, "build_pipeline", MajorityPredictions)

    result = evaluation.evaluate_split(
        examples,
        split,
        CATEGORIES,
        evaluated_at=datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert result.accuracy == pytest.approx(1 / 6)
    assert result.majority_baseline_accuracy == pytest.approx(1 / 6)
    assert result.beats_baseline is False


def test_evaluate_split_rejects_a_naive_evaluation_time() -> None:
    examples = [example(category, index) for category in CATEGORIES for index in range(2)]
    split = create_split(examples, CATEGORIES, seed=42, test_per_category=1)

    with pytest.raises(ValueError, match="timezone"):
        evaluation.evaluate_split(
            examples,
            split,
            CATEGORIES,
            evaluated_at=datetime(2026, 8, 18, 12, 0),
        )


def test_write_json_atomic_uses_stable_utf8_json(tmp_path: Path) -> None:
    report_path = tmp_path / "evaluation.json"

    evaluation.write_json_atomic(report_path, {"z": "中文", "a": 1})

    assert report_path.read_bytes() == b'{\n  "a": 1,\n  "z": "\xe4\xb8\xad\xe6\x96\x87"\n}\n'


def test_write_json_atomic_preserves_the_prior_report_when_promotion_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "evaluation.json"
    report_path.write_text("old report\n", encoding="utf-8")

    def replace_failure(self: Path, target: Path) -> Path:
        raise OSError("simulated promotion failure")

    monkeypatch.setattr(Path, "replace", replace_failure)

    with pytest.raises(OSError, match="simulated promotion failure"):
        evaluation.write_json_atomic(report_path, {"new": "report"})

    assert report_path.read_text(encoding="utf-8") == "old report\n"
