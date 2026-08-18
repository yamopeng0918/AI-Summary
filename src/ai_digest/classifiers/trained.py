"""Validated loading and promotion of accepted classifier artifacts."""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import joblib
import sklearn

from ai_digest.classifiers.dataset import (
    TrainingExample,
    approved_cohort,
    dataset_sha256,
)
from ai_digest.classifiers.evaluation import EvaluationResult, build_pipeline
from ai_digest.domain import DigestError


_MANIFEST_FIELDS = frozenset(
    {
        "schemaVersion",
        "categories",
        "datasetSha256",
        "seed",
        "modelParameters",
        "scikitLearnVersion",
        "trainedAt",
        "trainingExamples",
    }
)
_MODEL_PARAMETERS = {
    "tfidf": {"analyzer": "char_wb", "ngramRange": [2, 5]},
    "classifier": {"maxIter": 2000, "randomState": 42},
}
_DATASET_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _classifier_error(code: str, message: str) -> DigestError:
    return DigestError("classify", code, message, False)


def _not_found() -> DigestError:
    return _classifier_error("MODEL_NOT_FOUND", "Classifier model artifacts were not found")


def _load_failed() -> DigestError:
    return _classifier_error("PREDICTION_FAILED", "Classifier model could not be loaded")


def _prediction_failed() -> DigestError:
    return _classifier_error("PREDICTION_FAILED", "Classifier prediction failed")


def _save_failed() -> DigestError:
    return _classifier_error("PREDICTION_FAILED", "Classifier model could not be saved")


def _valid_model_parameters(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"tfidf", "classifier"}:
        return False
    tfidf = value.get("tfidf")
    classifier = value.get("classifier")
    return (
        isinstance(tfidf, dict)
        and set(tfidf) == {"analyzer", "ngramRange"}
        and tfidf.get("analyzer") == "char_wb"
        and isinstance(tfidf.get("analyzer"), str)
        and isinstance(tfidf.get("ngramRange"), list)
        and len(tfidf["ngramRange"]) == 2
        and all(type(item) is int for item in tfidf["ngramRange"])
        and tfidf["ngramRange"] == [2, 5]
        and isinstance(classifier, dict)
        and set(classifier) == {"maxIter", "randomState"}
        and type(classifier.get("maxIter")) is int
        and classifier.get("maxIter") == 2000
        and type(classifier.get("randomState")) is int
        and classifier.get("randomState") == 42
    )


def _validate_manifest(payload: Any, categories: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _load_failed()

    manifest_categories = payload.get("categories")
    if not isinstance(manifest_categories, list) or tuple(manifest_categories) != categories:
        raise _classifier_error(
            "CATEGORY_MISMATCH", "Classifier model categories do not match configuration"
        )

    model_version = payload.get("scikitLearnVersion")
    if not isinstance(model_version, str) or model_version != sklearn.__version__:
        raise _classifier_error(
            "MODEL_VERSION_MISMATCH", "Classifier model version is incompatible"
        )

    try:
        trained_at = datetime.fromisoformat(payload["trainedAt"])
    except (KeyError, TypeError, ValueError):
        raise _load_failed() from None

    if (
        set(payload) != _MANIFEST_FIELDS
        or type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != 1
        or not all(isinstance(category, str) and category for category in manifest_categories)
        or not isinstance(payload.get("datasetSha256"), str)
        or _DATASET_HASH.fullmatch(payload["datasetSha256"]) is None
        or type(payload.get("seed")) is not int
        or payload["seed"] != 42
        or not _valid_model_parameters(payload.get("modelParameters"))
        or trained_at.tzinfo is None
        or trained_at.utcoffset() is None
        or type(payload.get("trainingExamples")) is not int
        or payload["trainingExamples"] != 180
    ):
        raise _load_failed()
    return payload


class TrainedClassifier:
    """Load one repository-controlled model after validating its manifest."""

    def __init__(
        self, model_path: Path, manifest_path: Path, categories: Sequence[str]
    ) -> None:
        self._categories = tuple(categories)
        try:
            if not model_path.is_file() or not manifest_path.is_file():
                raise _not_found()
        except OSError:
            raise _not_found() from None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise _load_failed() from None
        _validate_manifest(manifest, self._categories)

        try:
            model = joblib.load(model_path)
            if not callable(getattr(model, "predict", None)):
                raise TypeError("model has no prediction interface")
        except Exception:
            raise _load_failed() from None
        self._model = model

    def predict(self, text: str) -> str:
        """Predict one configured category without exposing model failures."""
        if not isinstance(text, str) or not text.strip():
            raise _prediction_failed()
        try:
            predictions = self._model.predict([text])
            if len(predictions) != 1:
                raise ValueError("model returned an invalid number of predictions")
            prediction = predictions[0]
            if not isinstance(prediction, str) or prediction not in self._categories:
                raise ValueError("model returned an unknown category")
        except Exception:
            raise _prediction_failed() from None
        return prediction


def _temporary_path(path: Path, purpose: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.{purpose}-", suffix=".tmp", dir=path.parent
    )
    try:
        return Path(name)
    finally:
        # The caller writes through path-based APIs, so no descriptor remains open.
        os.close(descriptor)


def _backup(path: Path, owned_paths: list[Path]) -> Path | None:
    if not path.exists():
        return None
    backup_path = _temporary_path(path, "backup")
    owned_paths.append(backup_path)
    shutil.copyfile(path, backup_path)
    return backup_path


def _restore(path: Path, backup_path: Path | None) -> None:
    if backup_path is None:
        path.unlink(missing_ok=True)
    else:
        backup_path.replace(path)


def _restore_pair(
    model_path: Path,
    manifest_path: Path,
    model_backup: Path | None,
    manifest_backup: Path | None,
) -> None:
    restoration_error: OSError | None = None
    for path, backup_path in (
        (model_path, model_backup),
        (manifest_path, manifest_backup),
    ):
        try:
            _restore(path, backup_path)
        except OSError as error:
            restoration_error = restoration_error or error
    if restoration_error is not None:
        raise restoration_error


def save_accepted_model(
    examples: Sequence[TrainingExample],
    evaluation: EvaluationResult,
    categories: Sequence[str],
    model_path: Path,
    manifest_path: Path,
    trained_at: datetime,
) -> None:
    """Fit all approved rows and atomically promote a validated model pair."""
    if (
        not evaluation.beats_baseline
        or evaluation.accuracy <= evaluation.majority_baseline_accuracy
    ):
        raise _classifier_error(
            "EVALUATION_BELOW_BASELINE",
            "Classifier evaluation did not beat the majority baseline",
        )
    if trained_at.tzinfo is None or trained_at.utcoffset() is None:
        raise ValueError("training time must include a timezone offset")

    ordered_categories = tuple(categories)
    approved = approved_cohort(examples, ordered_categories, expected_per_category=30)
    approved_hash = dataset_sha256(approved)
    if evaluation.seed != 42 or evaluation.dataset_sha256 != approved_hash:
        raise _classifier_error("INVALID_DATASET", "Classifier dataset is invalid")

    model_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    owned_paths: list[Path] = []
    model_backup: Path | None = None
    manifest_backup: Path | None = None
    promotion_started = False
    try:
        pipeline = build_pipeline()
        pipeline.fit(
            [example.text for example in approved],
            [example.label for example in approved],
        )

        staged_model = _temporary_path(model_path, "stage")
        owned_paths.append(staged_model)
        staged_manifest = _temporary_path(manifest_path, "stage")
        owned_paths.append(staged_manifest)
        joblib.dump(pipeline, staged_model)
        manifest = {
            "schemaVersion": 1,
            "categories": list(ordered_categories),
            "datasetSha256": approved_hash,
            "seed": 42,
            "modelParameters": _MODEL_PARAMETERS,
            "scikitLearnVersion": sklearn.__version__,
            "trainedAt": trained_at.isoformat(),
            "trainingExamples": len(approved),
        }
        staged_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Validation happens while both production artifacts are still untouched.
        TrainedClassifier(staged_model, staged_manifest, ordered_categories)
        model_backup = _backup(model_path, owned_paths)
        manifest_backup = _backup(manifest_path, owned_paths)

        promotion_started = True
        staged_model.replace(model_path)
        staged_manifest.replace(manifest_path)
    except Exception:
        if promotion_started:
            try:
                _restore_pair(
                    model_path,
                    manifest_path,
                    model_backup,
                    manifest_backup,
                )
            except OSError:
                pass
        raise _save_failed() from None
    finally:
        for owned_path in owned_paths:
            try:
                owned_path.unlink(missing_ok=True)
            except OSError:
                pass
