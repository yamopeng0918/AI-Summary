import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pytest
import sklearn

from ai_digest.classifiers import trained
from ai_digest.classifiers.dataset import TrainingExample, dataset_sha256
from ai_digest.classifiers.evaluation import EvaluationResult, build_pipeline
from ai_digest.classifiers.trained import TrainedClassifier, save_accepted_model
from ai_digest.domain import DigestError


pytestmark = pytest.mark.filterwarnings(
    "ignore:Setting the shape on a NumPy array has been deprecated:DeprecationWarning"
)

CATEGORIES = tuple(
    json.loads(
        (Path(__file__).parents[1] / "data" / "categories.json").read_text(
            encoding="utf-8"
        )
    )
)
MODEL_PARAMETERS = {
    "tfidf": {"analyzer": "char_wb", "ngramRange": [2, 5]},
    "classifier": {"maxIter": 2000, "randomState": 42},
}
TRAINED_AT = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def fitted_pipeline() -> Any:
    pipeline = build_pipeline()
    texts: list[str] = []
    labels: list[str] = []
    phrases = {
        "人工智慧": "生成式 AI 模型與機器學習",
        "程式開發": "Python 測試與除錯實務",
        "科技產業": "半導體產業與科技市場",
        "商業與職場": "組織管理與求職面試",
        "設計與創意": "視覺設計與創意實作",
        "生活與學習": "個人成長與自主學習",
    }
    for category in CATEGORIES:
        for index in range(4):
            texts.append(f"{phrases[category]} {category} {index}")
            labels.append(category)
    pipeline.fit(texts, labels)
    return pipeline


def valid_manifest(**overrides: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "categories": list(CATEGORIES),
        "datasetSha256": "0" * 64,
        "seed": 42,
        "modelParameters": MODEL_PARAMETERS,
        "scikitLearnVersion": sklearn.__version__,
        "trainedAt": TRAINED_AT.isoformat(),
        "trainingExamples": 180,
    }
    manifest.update(overrides)
    return manifest


def write_artifacts(
    model_path: Path,
    manifest_path: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> None:
    joblib.dump(fitted_pipeline(), model_path)
    manifest_path.write_text(
        json.dumps(manifest or valid_manifest(), ensure_ascii=False), encoding="utf-8"
    )


def assert_safe_error(error: DigestError, code: str, message: str) -> None:
    assert error.as_dict() == {
        "stage": "classify",
        "code": code,
        "message": message,
        "retryable": False,
    }


def training_examples() -> list[TrainingExample]:
    return [
        TrainingExample(
            id=f"{category}-{index:02}",
            batch=(index // 10) + 1,
            text=f"{category} 分類主題與關鍵字 {index}",
            label=category,
            source_url=f"https://example.com/{CATEGORIES.index(category)}/{index}",
            source_title=f"{category} 來源 {index}",
            rationale="主題符合分類",
            review_status="approved",
            review_note="",
        )
        for category in CATEGORIES
        for index in range(30)
    ]


def accepted_evaluation(examples: list[TrainingExample], *, accepted: bool = True) -> EvaluationResult:
    return EvaluationResult(
        dataset_sha256=dataset_sha256(examples),
        split_sha256="1" * 64,
        seed=42,
        train_samples=144,
        test_samples=36,
        category_counts=(),
        accuracy=0.75 if accepted else 1 / 6,
        macro_f1=0.74 if accepted else 1 / 6,
        category_metrics=(),
        confusion_matrix=(),
        majority_baseline_accuracy=1 / 6,
        beats_baseline=accepted,
        evaluated_at=TRAINED_AT.isoformat(),
        evaluation_pipeline=None,
    )


def test_trained_classifier_loads_a_valid_artifact_and_predicts(tmp_path: Path) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path)

    classifier = TrainedClassifier(model_path, manifest_path, CATEGORIES)

    assert classifier.predict("Python 測試與除錯實務") == "程式開發"


@pytest.mark.parametrize("missing_name", ("classifier.joblib", "classifier-manifest.json"))
def test_trained_classifier_reports_absent_artifacts_safely(
    tmp_path: Path, missing_name: str
) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path)
    (tmp_path / missing_name).unlink()

    with pytest.raises(DigestError) as raised:
        TrainedClassifier(model_path, manifest_path, CATEGORIES)

    assert_safe_error(
        raised.value, "MODEL_NOT_FOUND", "Classifier model artifacts were not found"
    )
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.parametrize(
    ("overrides", "code", "message"),
    (
        (
            {"scikitLearnVersion": "0.0-secret-version"},
            "MODEL_VERSION_MISMATCH",
            "Classifier model version is incompatible",
        ),
        (
            {"categories": [*CATEGORIES[1:], CATEGORIES[0]]},
            "CATEGORY_MISMATCH",
            "Classifier model categories do not match configuration",
        ),
    ),
)
def test_manifest_is_validated_before_joblib_loading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, Any],
    code: str,
    message: str,
) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path, manifest=valid_manifest(**overrides))

    def unexpected_load(path: Path) -> Any:
        raise AssertionError("joblib.load must not run for an invalid manifest")

    monkeypatch.setattr(trained.joblib, "load", unexpected_load)

    with pytest.raises(DigestError) as raised:
        TrainedClassifier(model_path, manifest_path, CATEGORIES)

    assert_safe_error(raised.value, code, message)


@pytest.mark.parametrize(
    "overrides",
    (
        {"schemaVersion": 2},
        {"datasetSha256": "A" * 64},
        {"datasetSha256": "0" * 63},
        {"seed": 41},
        {"modelParameters": {}},
        {"trainedAt": "2026-08-18T12:00:00"},
        {"trainingExamples": 179},
    ),
)
def test_trained_classifier_rejects_invalid_manifest_metadata_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    model_path = tmp_path / "secret-model.joblib"
    manifest_path = tmp_path / "secret-manifest.json"
    write_artifacts(model_path, manifest_path, manifest=valid_manifest(**overrides))
    monkeypatch.setattr(
        trained.joblib,
        "load",
        lambda path: pytest.fail("invalid metadata must be rejected before deserialization"),
    )

    with pytest.raises(DigestError) as raised:
        TrainedClassifier(model_path, manifest_path, CATEGORIES)

    assert_safe_error(raised.value, "PREDICTION_FAILED", "Classifier model could not be loaded")
    assert "secret" not in str(raised.value)


def test_trained_classifier_converts_manifest_parse_and_model_load_failures_to_safe_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "secret-model.joblib"
    manifest_path = tmp_path / "secret-manifest.json"
    model_path.write_bytes(b"secret serialized marker")
    manifest_path.write_text("not valid secret json", encoding="utf-8")

    with pytest.raises(DigestError) as parse_error:
        TrainedClassifier(model_path, manifest_path, CATEGORIES)
    assert_safe_error(
        parse_error.value, "PREDICTION_FAILED", "Classifier model could not be loaded"
    )
    assert "secret" not in str(parse_error.value)

    manifest_path.write_text(json.dumps(valid_manifest()), encoding="utf-8")

    def load_failure(path: Path) -> Any:
        raise ValueError("secret serialized value")

    monkeypatch.setattr(trained.joblib, "load", load_failure)
    with pytest.raises(DigestError) as load_error:
        TrainedClassifier(model_path, manifest_path, CATEGORIES)
    assert_safe_error(load_error.value, "PREDICTION_FAILED", "Classifier model could not be loaded")
    assert "secret" not in str(load_error.value)


class RaisingPredictor:
    def predict(self, texts: list[str]) -> list[str]:
        raise RuntimeError("secret prediction payload")


class UnknownPredictor:
    def predict(self, texts: list[str]) -> list[str]:
        return ["secret unknown category"]


@pytest.mark.parametrize("text", ("", "   \n"))
def test_trained_classifier_rejects_blank_input(tmp_path: Path, text: str) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path)
    classifier = TrainedClassifier(model_path, manifest_path, CATEGORIES)

    with pytest.raises(DigestError) as raised:
        classifier.predict(text)

    assert_safe_error(raised.value, "PREDICTION_FAILED", "Classifier prediction failed")


@pytest.mark.parametrize("predictor", (RaisingPredictor(), UnknownPredictor()))
def test_trained_classifier_converts_predict_exceptions_and_unknown_outputs(
    tmp_path: Path, predictor: Any
) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path)
    classifier = TrainedClassifier(model_path, manifest_path, CATEGORIES)
    classifier._model = predictor

    with pytest.raises(DigestError) as raised:
        classifier.predict("secret input")

    assert_safe_error(raised.value, "PREDICTION_FAILED", "Classifier prediction failed")
    assert "secret" not in str(raised.value)


def test_save_accepted_model_rejects_below_baseline_before_changing_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path)
    old_model = model_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    examples = training_examples()
    monkeypatch.setattr(
        trained,
        "build_pipeline",
        lambda: pytest.fail("a rejected evaluation must not fit a production model"),
    )

    with pytest.raises(DigestError) as raised:
        save_accepted_model(
            examples,
            accepted_evaluation(examples, accepted=False),
            CATEGORIES,
            model_path,
            manifest_path,
            TRAINED_AT,
        )

    assert_safe_error(
        raised.value,
        "EVALUATION_BELOW_BASELINE",
        "Classifier evaluation did not beat the majority baseline",
    )
    assert model_path.read_bytes() == old_model
    assert manifest_path.read_bytes() == old_manifest


def test_save_accepted_model_writes_a_valid_reloadable_pair(tmp_path: Path) -> None:
    model_path = tmp_path / "models" / "classifier.joblib"
    manifest_path = tmp_path / "models" / "classifier-manifest.json"
    examples = training_examples()

    save_accepted_model(
        examples,
        accepted_evaluation(examples),
        CATEGORIES,
        model_path,
        manifest_path,
        TRAINED_AT,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    classifier = TrainedClassifier(model_path, manifest_path, CATEGORIES)
    assert manifest == valid_manifest(datasetSha256=dataset_sha256(examples))
    assert classifier.predict("程式開發 分類主題與關鍵字") == "程式開發"


def test_save_accepted_model_restores_both_old_artifacts_when_pair_promotion_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    write_artifacts(model_path, manifest_path)
    old_model = model_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    examples = training_examples()
    original_replace = Path.replace
    failed = False

    def fail_new_manifest_once(self: Path, target: Path) -> Path:
        nonlocal failed
        if not failed and target == manifest_path and ".stage-" in self.name:
            failed = True
            raise OSError("secret simulated promotion failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_new_manifest_once)

    with pytest.raises(DigestError) as raised:
        save_accepted_model(
            examples,
            accepted_evaluation(examples),
            CATEGORIES,
            model_path,
            manifest_path,
            TRAINED_AT,
        )

    assert_safe_error(raised.value, "PREDICTION_FAILED", "Classifier model could not be saved")
    assert "secret" not in str(raised.value)
    assert model_path.read_bytes() == old_model
    assert manifest_path.read_bytes() == old_manifest
    assert TrainedClassifier(model_path, manifest_path, CATEGORIES).predict(
        "Python 測試與除錯實務"
    ) == "程式開發"
    assert not (tmp_path / ".classifier.joblib.rollback-backup").exists()
    assert not (tmp_path / ".classifier-manifest.json.rollback-backup").exists()
    assert not list(tmp_path.glob(".*.stage-*.tmp"))
    assert not list(tmp_path.glob(".*.backup-*.tmp"))


def test_save_accepted_model_retains_deterministic_backups_when_rollback_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "classifier.joblib"
    manifest_path = tmp_path / "classifier-manifest.json"
    model_backup = tmp_path / ".classifier.joblib.rollback-backup"
    manifest_backup = tmp_path / ".classifier-manifest.json.rollback-backup"
    write_artifacts(model_path, manifest_path)
    old_model = model_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    examples = training_examples()
    original_replace = Path.replace
    original_copyfile = trained.shutil.copyfile
    promotion_failed = False
    rollback_failed = False

    def fail_manifest_promotion_and_model_restore(self: Path, target: Path) -> Path:
        nonlocal promotion_failed, rollback_failed
        if not promotion_failed and target == manifest_path and ".stage-" in self.name:
            promotion_failed = True
            raise OSError("secret simulated promotion failure")
        if promotion_failed and target == model_path and "backup" in self.name:
            rollback_failed = True
            raise OSError("secret simulated rollback failure")
        return original_replace(self, target)

    def fail_copied_model_restore(source: Path, target: Path) -> str:
        nonlocal rollback_failed
        if Path(source) == model_backup and Path(target) == model_path:
            rollback_failed = True
            raise OSError("secret simulated rollback failure")
        return original_copyfile(source, target)

    monkeypatch.setattr(Path, "replace", fail_manifest_promotion_and_model_restore)
    monkeypatch.setattr(trained.shutil, "copyfile", fail_copied_model_restore)

    with pytest.raises(DigestError) as raised:
        save_accepted_model(
            examples,
            accepted_evaluation(examples),
            CATEGORIES,
            model_path,
            manifest_path,
            TRAINED_AT,
        )

    assert promotion_failed is True
    assert rollback_failed is True
    assert_safe_error(raised.value, "PREDICTION_FAILED", "Classifier model could not be saved")
    assert "secret" not in str(raised.value)
    assert model_path.read_bytes() != old_model
    assert manifest_path.read_bytes() == old_manifest
    assert model_backup.read_bytes() == old_model
    assert manifest_backup.read_bytes() == old_manifest
    assert not list(tmp_path.glob(".*.stage-*.tmp"))
