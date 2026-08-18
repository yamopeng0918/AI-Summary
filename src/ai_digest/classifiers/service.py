"""Application service for reproducible classifier evaluation."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_digest.classifiers.dataset import TrainingExample, approved_cohort, load_dataset
from ai_digest.classifiers.evaluation import (
    EvaluationResult,
    SplitAssignment,
    create_split,
    evaluate_split,
    write_json_atomic,
)
from ai_digest.classifiers.trained import save_accepted_model
from ai_digest.domain import DigestError


def _category_mismatch() -> DigestError:
    return DigestError(
        "classify",
        "CATEGORY_MISMATCH",
        "Classifier categories do not match configuration",
        False,
    )


def _load_categories(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise _category_mismatch() from None
    if (
        not isinstance(payload, list)
        or not payload
        or any(not isinstance(category, str) or not category for category in payload)
        or len(set(payload)) != len(payload)
    ):
        raise _category_mismatch()
    return tuple(payload)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _persisted_split_matches(path: Path, expected: SplitAssignment) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return _canonical_json(payload) == _canonical_json(expected.as_dict())


class ClassifierEvaluationService:
    """Validate data, evaluate one split, persist its report, and promote accepted models."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        dataset_path: Path = Path("data/classifier/training.csv"),
        category_path: Path = Path("data/categories.json"),
        split_path: Path = Path("data/classifier/split.json"),
        report_path: Path = Path("data/classifier/evaluation.json"),
        model_path: Path = Path("models/classifier.joblib"),
        manifest_path: Path = Path("models/classifier-manifest.json"),
        category_loader: Callable[[Path], Sequence[str]] = _load_categories,
        dataset_loader: Callable[[Path, Sequence[str]], list[TrainingExample]] = load_dataset,
        cohort_selector: Callable[
            [Sequence[TrainingExample], Sequence[str], int], list[TrainingExample]
        ] = approved_cohort,
        split_creator: Callable[..., SplitAssignment] = create_split,
        evaluator: Callable[..., EvaluationResult] = evaluate_split,
        json_writer: Callable[
            [Path, Mapping[str, Any] | SplitAssignment | EvaluationResult], None
        ] = write_json_atomic,
        model_saver: Callable[..., None] = save_accepted_model,
    ) -> None:
        self.clock = clock
        self.dataset_path = dataset_path
        self.category_path = category_path
        self.split_path = split_path
        self.report_path = report_path
        self.model_path = model_path
        self.manifest_path = manifest_path
        self._category_loader = category_loader
        self._dataset_loader = dataset_loader
        self._cohort_selector = cohort_selector
        self._split_creator = split_creator
        self._evaluator = evaluator
        self._json_writer = json_writer
        self._model_saver = model_saver

    def run(self) -> EvaluationResult:
        categories = tuple(self._category_loader(self.category_path))
        examples = self._dataset_loader(self.dataset_path, categories)
        cohort = self._cohort_selector(examples, categories, 30)
        split = self._split_creator(cohort, categories, seed=42, test_per_category=6)
        if not _persisted_split_matches(self.split_path, split):
            self.split_path.parent.mkdir(parents=True, exist_ok=True)
            self._json_writer(self.split_path, split)

        now = self.clock()
        result = self._evaluator(cohort, split, categories, evaluated_at=now)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self._json_writer(self.report_path, result)
        if (
            not result.beats_baseline
            or result.accuracy <= result.majority_baseline_accuracy
        ):
            raise DigestError(
                "classify",
                "EVALUATION_BELOW_BASELINE",
                "Classifier evaluation did not beat the majority baseline",
                False,
            )

        self._model_saver(
            cohort,
            result,
            categories,
            self.model_path,
            self.manifest_path,
            now,
        )
        return result

    def cli_payload(self, result: EvaluationResult) -> dict[str, object]:
        """Return the concise machine-readable command result."""
        return {
            "accuracy": result.accuracy,
            "macroF1": result.macro_f1,
            "majorityBaselineAccuracy": result.majority_baseline_accuracy,
            "beatsBaseline": result.beats_baseline,
            "datasetPath": self.dataset_path.as_posix(),
            "categoryPath": self.category_path.as_posix(),
            "splitPath": self.split_path.as_posix(),
            "reportPath": self.report_path.as_posix(),
            "modelPath": self.model_path.as_posix(),
            "manifestPath": self.manifest_path.as_posix(),
        }
