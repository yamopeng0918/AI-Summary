"""Reproducible classifier split assignment and held-out evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import Pipeline

from ai_digest.classifiers.dataset import TrainingExample, dataset_sha256
from ai_digest.domain import DigestError


def _invalid_dataset() -> DigestError:
    return DigestError("classify", "INVALID_DATASET", "Classifier dataset is invalid", False)


@dataclass(frozen=True, slots=True)
class CategoryCounts:
    """Train and test counts for one configured category."""

    category: str
    train: int
    test: int

    def as_dict(self) -> dict[str, int]:
        return {"train": self.train, "test": self.test}


@dataclass(frozen=True, slots=True)
class SplitAssignment:
    """A deterministic partition of one approved training cohort."""

    seed: int
    dataset_sha256: str
    train_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    category_counts: tuple[CategoryCounts, ...]

    @property
    def split_sha256(self) -> str:
        """Return the stable hash of the persisted split assignment."""
        encoded = json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON representation used by the evaluation artifacts."""
        return {
            "seed": self.seed,
            "datasetSha256": self.dataset_sha256,
            "trainIds": list(self.train_ids),
            "testIds": list(self.test_ids),
            "perCategoryCounts": {
                count.category: count.as_dict() for count in self.category_counts
            },
        }


@dataclass(frozen=True, slots=True)
class CategoryMetrics:
    """Held-out classification metrics for one configured category."""

    category: str
    precision: float
    recall: float
    f1: float
    support: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "support": self.support,
        }


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """JSON-ready held-out metrics plus the pipeline fitted for evaluation."""

    dataset_sha256: str
    split_sha256: str
    seed: int
    train_samples: int
    test_samples: int
    category_counts: tuple[CategoryCounts, ...]
    accuracy: float
    macro_f1: float
    category_metrics: tuple[CategoryMetrics, ...]
    confusion_matrix: tuple[tuple[int, ...], ...]
    majority_baseline_accuracy: float
    beats_baseline: bool
    evaluated_at: str
    evaluation_pipeline: Any

    def as_dict(self) -> dict[str, Any]:
        """Return a report payload without the non-serializable fitted pipeline."""
        return {
            "datasetSha256": self.dataset_sha256,
            "splitSha256": self.split_sha256,
            "seed": self.seed,
            "modelParameters": {
                "tfidf": {"analyzer": "char_wb", "ngramRange": [2, 5]},
                "classifier": {"maxIter": 2000, "randomState": 42},
            },
            "trainingSamples": self.train_samples,
            "testSamples": self.test_samples,
            "perCategoryCounts": {
                count.category: count.as_dict() for count in self.category_counts
            },
            "accuracy": self.accuracy,
            "macroF1": self.macro_f1,
            "perCategoryMetrics": {
                metric.category: metric.as_dict() for metric in self.category_metrics
            },
            "confusionMatrix": [list(row) for row in self.confusion_matrix],
            "majorityBaselineAccuracy": self.majority_baseline_accuracy,
            "beatsBaseline": self.beats_baseline,
            "accepted": self.beats_baseline,
            "pythonVersion": platform.python_version(),
            "scikitLearnVersion": sklearn.__version__,
            "evaluatedAt": self.evaluated_at,
        }


def _validate_categories(categories: Sequence[str]) -> tuple[str, ...]:
    ordered_categories = tuple(categories)
    if not ordered_categories or any(not category for category in ordered_categories):
        raise _invalid_dataset()
    if len(set(ordered_categories)) != len(ordered_categories):
        raise _invalid_dataset()
    return ordered_categories


def _examples_by_id(
    examples: Sequence[TrainingExample], categories: Sequence[str]
) -> dict[str, TrainingExample]:
    category_set = set(categories)
    examples_by_id: dict[str, TrainingExample] = {}
    for example in examples:
        if (
            not example.id
            or example.id in examples_by_id
            or example.label not in category_set
            or example.review_status != "approved"
        ):
            raise _invalid_dataset()
        examples_by_id[example.id] = example
    return examples_by_id


def create_split(
    examples: Sequence[TrainingExample],
    categories: Sequence[str],
    *,
    seed: int,
    test_per_category: int,
) -> SplitAssignment:
    """Create a stable stratified assignment independent of CSV row order."""
    ordered_categories = _validate_categories(categories)
    if test_per_category < 1:
        raise _invalid_dataset()
    _examples_by_id(examples, ordered_categories)

    train_ids: list[str] = []
    test_ids: list[str] = []
    category_counts: list[CategoryCounts] = []
    for category in ordered_categories:
        identifiers = sorted(example.id for example in examples if example.label == category)
        if len(identifiers) <= test_per_category:
            raise _invalid_dataset()
        random.Random(f"{seed}:{category}").shuffle(identifiers)
        category_test_ids = identifiers[:test_per_category]
        category_train_ids = identifiers[test_per_category:]
        train_ids.extend(category_train_ids)
        test_ids.extend(category_test_ids)
        category_counts.append(
            CategoryCounts(category, train=len(category_train_ids), test=len(category_test_ids))
        )

    return SplitAssignment(
        seed=seed,
        dataset_sha256=dataset_sha256(examples),
        train_ids=tuple(train_ids),
        test_ids=tuple(test_ids),
        category_counts=tuple(category_counts),
    )


def build_pipeline() -> Pipeline:
    """Build the approved classifier pipeline with fixed reproducibility settings."""
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))),
            ("classifier", LogisticRegression(max_iter=2000, random_state=42)),
        ]
    )


def _validate_split(
    examples_by_id: Mapping[str, TrainingExample], split: SplitAssignment
) -> None:
    assigned_ids = (*split.train_ids, *split.test_ids)
    if (
        not split.train_ids
        or not split.test_ids
        or len(assigned_ids) != len(set(assigned_ids))
        or set(assigned_ids) != set(examples_by_id)
        or split.dataset_sha256 != dataset_sha256(tuple(examples_by_id.values()))
    ):
        raise _invalid_dataset()


def _validate_evaluated_at(evaluated_at: datetime) -> str:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluation time must include a timezone offset")
    return evaluated_at.isoformat()


def evaluate_split(
    examples: Sequence[TrainingExample],
    split: SplitAssignment,
    categories: Sequence[str],
    *,
    evaluated_at: datetime,
) -> EvaluationResult:
    """Fit on one split partition and calculate configured-label held-out metrics."""
    ordered_categories = _validate_categories(categories)
    examples_by_id = _examples_by_id(examples, ordered_categories)
    _validate_split(examples_by_id, split)
    evaluated_at_value = _validate_evaluated_at(evaluated_at)

    train_examples = [examples_by_id[identifier] for identifier in split.train_ids]
    test_examples = [examples_by_id[identifier] for identifier in split.test_ids]
    pipeline = build_pipeline()
    pipeline.fit(
        [example.text for example in train_examples],
        [example.label for example in train_examples],
    )
    expected_labels = [example.label for example in test_examples]
    predicted_labels = list(pipeline.predict([example.text for example in test_examples]))

    precision, recall, f1, support = precision_recall_fscore_support(
        expected_labels,
        predicted_labels,
        labels=ordered_categories,
        zero_division=0,
    )
    category_metrics = tuple(
        CategoryMetrics(
            category=category,
            precision=float(precision[index]),
            recall=float(recall[index]),
            f1=float(f1[index]),
            support=int(support[index]),
        )
        for index, category in enumerate(ordered_categories)
    )
    category_counts = tuple(
        CategoryCounts(
            category=category,
            train=sum(example.label == category for example in train_examples),
            test=sum(example.label == category for example in test_examples),
        )
        for category in ordered_categories
    )
    accuracy = float(accuracy_score(expected_labels, predicted_labels))
    majority_baseline = max(count.test for count in category_counts) / len(test_examples)

    return EvaluationResult(
        dataset_sha256=split.dataset_sha256,
        split_sha256=split.split_sha256,
        seed=split.seed,
        train_samples=len(train_examples),
        test_samples=len(test_examples),
        category_counts=category_counts,
        accuracy=accuracy,
        macro_f1=float(sum(metric.f1 for metric in category_metrics) / len(category_metrics)),
        category_metrics=category_metrics,
        confusion_matrix=tuple(
            tuple(int(value) for value in row)
            for row in confusion_matrix(expected_labels, predicted_labels, labels=ordered_categories)
        ),
        majority_baseline_accuracy=majority_baseline,
        beats_baseline=accuracy > majority_baseline,
        evaluated_at=evaluated_at_value,
        evaluation_pipeline=pipeline,
    )


def write_json_atomic(path: Path, payload: Mapping[str, Any] | SplitAssignment | EvaluationResult) -> None:
    """Write JSON through a sibling temporary file without corrupting prior output."""
    serializable_payload = payload.as_dict() if hasattr(payload, "as_dict") else payload
    encoded = json.dumps(
        serializable_payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(encoded)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
