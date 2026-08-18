import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ai_digest.classifiers.evaluation import (
    CategoryCounts,
    CategoryMetrics,
    EvaluationResult,
    SplitAssignment,
)
from ai_digest.classifiers.service import ClassifierEvaluationService
from ai_digest.domain import DigestError


TAIPEI = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 18, 10, 30, tzinfo=TAIPEI)
CATEGORIES = (
    "人工智慧",
    "程式開發",
    "科技產業",
    "商業與職場",
    "設計與創意",
    "生活與學習",
)


def make_split() -> SplitAssignment:
    return SplitAssignment(
        seed=42,
        dataset_sha256="a" * 64,
        train_ids=tuple(f"train-{index}" for index in range(6)),
        test_ids=tuple(f"test-{index}" for index in range(6)),
        category_counts=tuple(CategoryCounts(category, train=1, test=1) for category in CATEGORIES),
    )


def make_result(*, beats_baseline: bool = True) -> EvaluationResult:
    accuracy = 0.75 if beats_baseline else (1 / 6)
    return EvaluationResult(
        dataset_sha256="a" * 64,
        split_sha256=make_split().split_sha256,
        seed=42,
        train_samples=6,
        test_samples=6,
        category_counts=tuple(CategoryCounts(category, train=1, test=1) for category in CATEGORIES),
        accuracy=accuracy,
        macro_f1=0.7 if beats_baseline else 0.05,
        category_metrics=tuple(
            CategoryMetrics(category, precision=0.7, recall=0.7, f1=0.7, support=1)
            for category in CATEGORIES
        ),
        confusion_matrix=tuple(tuple(int(row == column) for column in range(6)) for row in range(6)),
        majority_baseline_accuracy=1 / 6,
        beats_baseline=beats_baseline,
        evaluated_at=NOW.isoformat(),
        evaluation_pipeline=object(),
    )


def make_service(
    tmp_path: Path,
    events: list[str],
    *,
    result: EvaluationResult | None = None,
) -> tuple[ClassifierEvaluationService, SplitAssignment]:
    split = make_split()
    split_path = tmp_path / "data" / "classifier" / "split.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text(json.dumps(split.as_dict()), encoding="utf-8")
    evaluation_result = result or make_result()
    examples = [object()]
    cohort = [object()]

    def category_loader(path: Path):
        assert path == tmp_path / "data" / "categories.json"
        return CATEGORIES

    def dataset_loader(path: Path, categories):
        events.append("load")
        assert path == tmp_path / "data" / "classifier" / "training.csv"
        assert tuple(categories) == CATEGORIES
        return examples

    def cohort_selector(loaded, categories, expected_per_category: int):
        events.append("cohort")
        assert loaded is examples
        assert tuple(categories) == CATEGORIES
        assert expected_per_category == 30
        return cohort

    def split_creator(approved, categories, *, seed: int, test_per_category: int):
        events.append("split")
        assert approved is cohort
        assert tuple(categories) == CATEGORIES
        assert seed == 42
        assert test_per_category == 6
        return split

    def evaluator(approved, assignment, categories, *, evaluated_at: datetime):
        events.append("evaluate")
        assert approved is cohort
        assert assignment is split
        assert tuple(categories) == CATEGORIES
        assert evaluated_at == NOW
        return evaluation_result

    def json_writer(path: Path, payload):
        if path == tmp_path / "data" / "classifier" / "evaluation.json":
            events.append("report")
            assert payload is evaluation_result
        else:
            events.append("split-write")
            assert path == split_path
            assert payload is split

    def model_saver(approved, evaluation, categories, model_path, manifest_path, trained_at):
        events.append("model")
        assert approved is cohort
        assert evaluation is evaluation_result
        assert tuple(categories) == CATEGORIES
        assert model_path == tmp_path / "models" / "classifier.joblib"
        assert manifest_path == tmp_path / "models" / "classifier-manifest.json"
        assert trained_at == NOW

    service = ClassifierEvaluationService(
        clock=lambda: NOW,
        dataset_path=tmp_path / "data" / "classifier" / "training.csv",
        category_path=tmp_path / "data" / "categories.json",
        split_path=split_path,
        report_path=tmp_path / "data" / "classifier" / "evaluation.json",
        model_path=tmp_path / "models" / "classifier.joblib",
        manifest_path=tmp_path / "models" / "classifier-manifest.json",
        category_loader=category_loader,
        dataset_loader=dataset_loader,
        cohort_selector=cohort_selector,
        split_creator=split_creator,
        evaluator=evaluator,
        json_writer=json_writer,
        model_saver=model_saver,
    )
    return service, split


def test_service_orchestrates_evaluation_and_saves_model_only_after_passing_report(tmp_path: Path) -> None:
    events: list[str] = []
    service, _ = make_service(tmp_path, events)

    result = service.run()

    assert events == ["load", "cohort", "split", "evaluate", "report", "model"]
    assert result.beats_baseline is True


def test_service_persists_failed_report_and_does_not_replace_model(tmp_path: Path) -> None:
    events: list[str] = []
    service, _ = make_service(tmp_path, events, result=make_result(beats_baseline=False))

    with pytest.raises(DigestError) as raised:
        service.run()

    assert raised.value.as_dict() == {
        "stage": "classify",
        "code": "EVALUATION_BELOW_BASELINE",
        "message": "Classifier evaluation did not beat the majority baseline",
        "retryable": False,
    }
    assert events == ["load", "cohort", "split", "evaluate", "report"]


def _tamper_split(payload: dict[str, object], mismatch: str) -> None:
    if mismatch == "dataset-hash":
        payload["datasetSha256"] = "b" * 64
    elif mismatch == "seed":
        payload["seed"] = 7
    elif mismatch == "seed-type":
        payload["seed"] = True
    elif mismatch == "ids":
        payload["trainIds"] = ["foreign", *payload["trainIds"][1:]]  # type: ignore[index]
    elif mismatch == "assignments":
        train_ids = payload["trainIds"]  # type: ignore[assignment]
        test_ids = payload["testIds"]  # type: ignore[assignment]
        train_ids[0], test_ids[0] = test_ids[0], train_ids[0]
    elif mismatch == "counts":
        counts = payload["perCategoryCounts"]  # type: ignore[assignment]
        counts[CATEGORIES[0]]["train"] = 99
    elif mismatch == "extra-field":
        payload["unexpected"] = True
    else:
        raise AssertionError(f"unknown mismatch: {mismatch}")


@pytest.mark.parametrize(
    "mismatch",
    (
        "dataset-hash",
        "seed",
        "seed-type",
        "ids",
        "assignments",
        "counts",
        "extra-field",
    ),
)
def test_service_regenerates_persisted_split_when_any_exact_field_mismatches(
    tmp_path: Path,
    mismatch: str,
) -> None:
    events: list[str] = []
    service, split = make_service(tmp_path, events)
    payload = copy.deepcopy(split.as_dict())
    _tamper_split(payload, mismatch)
    service.split_path.write_text(json.dumps(payload), encoding="utf-8")

    service.run()

    assert events == [
        "load",
        "cohort",
        "split",
        "split-write",
        "evaluate",
        "report",
        "model",
    ]


@pytest.mark.parametrize("persisted", ("missing", "malformed"))
def test_service_regenerates_a_missing_or_malformed_split(tmp_path: Path, persisted: str) -> None:
    events: list[str] = []
    service, _ = make_service(tmp_path, events)
    if persisted == "missing":
        service.split_path.unlink()
    else:
        service.split_path.write_text("not json", encoding="utf-8")

    service.run()

    assert "split-write" in events
    assert events.index("split-write") < events.index("evaluate")


def test_service_uses_repository_relative_artifact_defaults() -> None:
    service = ClassifierEvaluationService(clock=lambda: NOW)

    assert service.dataset_path == Path("data/classifier/training.csv")
    assert service.category_path == Path("data/categories.json")
    assert service.split_path == Path("data/classifier/split.json")
    assert service.report_path == Path("data/classifier/evaluation.json")
    assert service.model_path == Path("models/classifier.joblib")
    assert service.manifest_path == Path("models/classifier-manifest.json")


def test_service_reports_invalid_category_configuration_safely(tmp_path: Path) -> None:
    category_path = tmp_path / "categories.json"
    category_path.write_text("not json", encoding="utf-8")
    service = ClassifierEvaluationService(clock=lambda: NOW, category_path=category_path)

    with pytest.raises(DigestError) as raised:
        service.run()

    assert raised.value.as_dict() == {
        "stage": "classify",
        "code": "CATEGORY_MISMATCH",
        "message": "Classifier categories do not match configuration",
        "retryable": False,
    }


def test_service_cli_payload_contains_metrics_and_all_artifact_paths() -> None:
    service = ClassifierEvaluationService(clock=lambda: NOW)

    payload = service.cli_payload(make_result())

    assert payload == {
        "accuracy": 0.75,
        "macroF1": 0.7,
        "majorityBaselineAccuracy": 1 / 6,
        "beatsBaseline": True,
        "datasetPath": "data/classifier/training.csv",
        "categoryPath": "data/categories.json",
        "splitPath": "data/classifier/split.json",
        "reportPath": "data/classifier/evaluation.json",
        "modelPath": "models/classifier.joblib",
        "manifestPath": "models/classifier-manifest.json",
    }
