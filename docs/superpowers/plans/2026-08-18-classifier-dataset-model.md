# Classifier Dataset and Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, review, evaluate, and deploy a reproducible six-category Traditional Chinese article classifier whose held-out Accuracy is strictly higher than the majority-class baseline.

**Architecture:** Keep dataset parsing, deterministic splitting/evaluation, serialized-model loading, and CLI composition in separate modules. The evaluator consumes only approved CSV rows, saves reproducible JSON artifacts, and replaces the production model atomically only after acceptance; the runtime adapter implements the existing `Classifier.predict(text) -> str` boundary and never fetches or stores content.

**Tech Stack:** Python 3.12+, Pydantic 2, Typer, scikit-learn 1.9.x, joblib 1.5.x, pytest, CSV and JSON version-controlled artifacts.

## Global Constraints

- The configured category order comes from `data/categories.json`: `人工智慧`, `程式開發`, `科技產業`, `商業與職場`, `設計與創意`, `生活與學習`.
- The approved cohort contains exactly 180 unique public-source examples, 30 per category, delivered as three review batches of 60; rejected historical rows may remain in the CSV.
- Only `reviewStatus=approved` rows enter training or evaluation.
- Use random seed `42`, with 24 training and 6 held-out test examples per category.
- Use `TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))` and `LogisticRegression(max_iter=2000, random_state=42)` without tokenization, tuning, or fallback models.
- Acceptance requires `accuracy > majorityBaselineAccuracy`; a failed evaluation saves its report but must not overwrite the last accepted model.
- All generated timestamps are timezone-aware ISO 8601 values using `Asia/Taipei` by default.
- Daily automated tests use local fixtures only and require neither network access nor a paid API.
- Source research may include only directly readable public pages and must not bypass login, paywalls, robots, anti-bot controls, or private-content restrictions.
- Preserve unrelated user files and changes; each commit includes only the files listed by its task.

---

### Task 1: Dataset schema and validation

**Files:**
- Modify: `pyproject.toml`
- Create: `src/ai_digest/classifiers/dataset.py`
- Create: `tests/fixtures/classifier/training-small.csv`
- Create: `tests/test_classifier_dataset.py`

**Interfaces:**
- Consumes: ordered `Sequence[str]` categories and a CSV `Path`.
- Produces: immutable `TrainingExample`, `load_dataset(path, categories) -> list[TrainingExample]`, `approved_cohort(examples, categories, expected_per_category) -> list[TrainingExample]`, and `dataset_sha256(examples) -> str`.

- [ ] **Step 1: Declare the model dependencies and write the failing happy-path test**

Add `scikit-learn>=1.9,<2` and `joblib>=1.5,<2` to `[project].dependencies`. Create a six-row UTF-8 fixture with this exact header:

```csv
id,batch,text,label,sourceUrl,sourceTitle,rationale,reviewStatus,reviewNote
```

Write a test that loads one approved example for every configured category and asserts field normalization and stable ordering:

```python
def test_load_dataset_parses_utf8_rows_in_file_order() -> None:
    rows = load_dataset(FIXTURE_ROOT / "training-small.csv", CATEGORIES)
    assert [row.id for row in rows] == [f"example-{index}" for index in range(1, 7)]
    assert [row.label for row in rows] == list(CATEGORIES)
    assert all(row.review_status == "approved" for row in rows)
```

- [ ] **Step 2: Run the focused test and confirm the missing module failure**

Run: `python -m pytest tests/test_classifier_dataset.py::test_load_dataset_parses_utf8_rows_in_file_order -v`

Expected: FAIL because `ai_digest.classifiers.dataset` does not exist.

- [ ] **Step 3: Implement the immutable row model and CSV loader**

Implement `TrainingExample` as a frozen dataclass with snake-case Python fields mapped from the exact CSV header. Strip scalar whitespace, parse `batch` as `int`, require batch in `{1, 2, 3}`, require an HTTP(S) URL with a non-empty host, and convert validation/CSV failures to safe `DigestError("classify", "INVALID_DATASET", "Classifier dataset is invalid", False)` without including row content or URLs.

```python
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
```

- [ ] **Step 4: Add failing validation tests**

Use `tmp_path` to cover missing/extra headers, blank required fields, invalid batch/review state, unknown label, non-HTTP URL, duplicate ID, and duplicate canonical source URL. Assert the exact safe code and that the exception does not contain fixture text:

```python
with pytest.raises(DigestError) as raised:
    load_dataset(path, CATEGORIES)
assert (raised.value.stage, raised.value.code) == ("classify", "INVALID_DATASET")
assert "secret-row-marker" not in str(raised.value)
```

- [ ] **Step 5: Implement cohort validation and canonical duplicate detection**

Canonicalize comparison keys as lowercase scheme/host, remove fragments, preserve path/query, and treat one trailing slash as equivalent. Implement approved-only filtering; raise `UNAPPROVED_DATA` if final evaluation is requested before exact counts, `CATEGORY_MISMATCH` for category-set disagreement, and `INSUFFICIENT_SAMPLES` for a class count below `expected_per_category`.

```python
def approved_cohort(
    examples: Sequence[TrainingExample],
    categories: Sequence[str],
    expected_per_category: int,
) -> list[TrainingExample]:
    """Return approved rows only after enforcing exact per-category counts."""
```

- [ ] **Step 6: Implement and test a stable dataset content hash**

Hash the UTF-8 JSON encoding of approved rows sorted by immutable `id`, using sorted keys and compact separators. Test that input row order does not change the hash but changing `text`, `label`, or `sourceUrl` does.

```python
def dataset_sha256(examples: Sequence[TrainingExample]) -> str:
    payload = json.dumps(serialized_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 7: Run focused tests and commit**

Run: `python -m pytest tests/test_classifier_dataset.py -v`

Expected: all dataset tests PASS.

Run: `git diff --check`

Commit:

```powershell
git add pyproject.toml src/ai_digest/classifiers/dataset.py tests/fixtures/classifier/training-small.csv tests/test_classifier_dataset.py
git commit -m "feat: validate classifier training data"
```

### Task 2: Deterministic split and evaluation report

**Files:**
- Create: `src/ai_digest/classifiers/evaluation.py`
- Create: `tests/test_classifier_evaluation.py`

**Interfaces:**
- Consumes: approved `Sequence[TrainingExample]`, ordered categories, seed, and aware evaluation time.
- Produces: `SplitAssignment`, `EvaluationResult`, `create_split(...)`, `evaluate_split(...)`, `write_json_atomic(...)`, and `build_pipeline()`.

- [ ] **Step 1: Write a failing deterministic split test**

Build a local in-memory fixture with 10 examples per category and assert eight train/two test IDs per class, no overlap, full coverage, and identical output after reversing input order:

```python
first = create_split(examples, CATEGORIES, seed=42, test_per_category=2)
second = create_split(list(reversed(examples)), CATEGORIES, seed=42, test_per_category=2)
assert first == second
assert set(first.train_ids).isdisjoint(first.test_ids)
assert len(first.train_ids) == 48
assert len(first.test_ids) == 12
```

- [ ] **Step 2: Run the split test and confirm failure**

Run: `python -m pytest tests/test_classifier_evaluation.py::test_create_split_is_stratified_and_order_independent -v`

Expected: FAIL because the evaluation module is missing.

- [ ] **Step 3: Implement deterministic per-category splitting**

Sort examples by ID before applying a seed-derived `random.Random` shuffle independently per category. Return frozen tuples and serialize `seed`, `datasetSha256`, ordered `trainIds`, ordered `testIds`, and per-category counts. Reject missing, duplicated, or foreign IDs with `INVALID_DATASET`.

```python
@dataclass(frozen=True, slots=True)
class SplitAssignment:
    seed: int
    dataset_sha256: str
    train_ids: tuple[str, ...]
    test_ids: tuple[str, ...]

def create_split(examples, categories, *, seed: int, test_per_category: int) -> SplitAssignment:
    """Create a stable stratified assignment independent of CSV row order."""
```

- [ ] **Step 4: Write the failing metrics test**

Use a fixed small dataset and monkeypatch `build_pipeline()` with a deterministic fake estimator. Assert Accuracy, Macro F1, every per-class precision/recall/F1/support, category-ordered confusion matrix, majority baseline, and strict acceptance:

```python
result = evaluate_split(examples, split, CATEGORIES, evaluated_at=NOW)
assert result.accuracy == pytest.approx(5 / 6)
assert result.majority_baseline_accuracy == pytest.approx(1 / 6)
assert result.beats_baseline is True
assert result.confusion_matrix == expected_matrix
assert result.evaluated_at == "2026-08-18T12:00:00+08:00"
```

- [ ] **Step 5: Implement the exact pipeline and report calculation**

Create a scikit-learn `Pipeline` named `tfidf`/`classifier`, calculate metrics with the explicit configured label order and `zero_division=0`, and reject naive timestamps. Keep both fitted evaluation pipeline and JSON-serializable result available to the orchestration layer.

```python
def build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))),
        ("classifier", LogisticRegression(max_iter=2000, random_state=42)),
    ])
```

- [ ] **Step 6: Test strict baseline equality and atomic JSON writes**

Add a prediction fixture where Accuracy equals the baseline and assert `beats_baseline is False`. Patch `Path.replace` failure to confirm the prior report remains intact; successful writes must use UTF-8, `ensure_ascii=False`, sorted keys, two-space indentation, and a final newline.

- [ ] **Step 7: Run focused tests and commit**

Run: `python -m pytest tests/test_classifier_evaluation.py -v`

Expected: all evaluation tests PASS.

Commit:

```powershell
git add src/ai_digest/classifiers/evaluation.py tests/test_classifier_evaluation.py
git commit -m "feat: evaluate classifier reproducibly"
```

### Task 3: Accepted model artifacts and runtime adapter

**Files:**
- Create: `src/ai_digest/classifiers/trained.py`
- Create: `tests/test_trained_classifier.py`

**Interfaces:**
- Consumes: repository-controlled model and manifest paths plus ordered categories.
- Produces: `TrainedClassifier(model_path, manifest_path, categories)` and `save_accepted_model(...)`.

- [ ] **Step 1: Write failing runtime adapter tests**

Serialize only a test-owned fitted pipeline. Assert valid prediction, and exact safe errors for absent files (`MODEL_NOT_FOUND`), scikit-learn version mismatch (`MODEL_VERSION_MISMATCH`), category-order mismatch (`CATEGORY_MISMATCH`), blank input/predict exception/unknown output (`PREDICTION_FAILED`).

```python
classifier = TrainedClassifier(model_path, manifest_path, CATEGORIES)
assert classifier.predict("Python 測試與除錯實務") == "程式開發"
```

- [ ] **Step 2: Run the focused adapter test and confirm failure**

Run: `python -m pytest tests/test_trained_classifier.py -v`

Expected: FAIL because `TrainedClassifier` is not defined.

- [ ] **Step 3: Implement manifest validation before model loading**

Read manifest JSON first and verify `schemaVersion=1`, exact category order, installed scikit-learn version, 64-character lowercase dataset hash, seed `42`, model parameters, aware `trainedAt`, and `trainingExamples=180`. Load only the configured repository path with `joblib.load`; convert parse/load/predict exceptions to safe structured classifier errors without exposing paths or serialized values.

```python
class TrainedClassifier:
    def __init__(self, model_path: Path, manifest_path: Path, categories: Sequence[str]) -> None: ...
    def predict(self, text: str) -> str: ...
```

- [ ] **Step 4: Write failing accepted-save rollback tests**

Pre-create a valid old model/manifest. Simulate failure during the new pair promotion and assert both old artifacts still load. Assert a below-baseline result raises `EVALUATION_BELOW_BASELINE` before either production path changes.

- [ ] **Step 5: Implement paired artifact staging and promotion**

Fit a fresh production pipeline on all 180 approved examples only after acceptance, write model and manifest to sibling temporary paths, reload and validate the staged pair, then replace the production pair. On failure, restore the old pair from sibling backups and remove only task-owned temporary files.

```python
def save_accepted_model(
    examples: Sequence[TrainingExample],
    evaluation: EvaluationResult,
    categories: Sequence[str],
    model_path: Path,
    manifest_path: Path,
    trained_at: datetime,
) -> None:
    """Fit all approved rows and atomically promote a validated model pair."""
```

- [ ] **Step 6: Run focused tests and commit**

Run: `python -m pytest tests/test_trained_classifier.py -v`

Expected: all trained-classifier tests PASS.

Commit:

```powershell
git add src/ai_digest/classifiers/trained.py tests/test_trained_classifier.py
git commit -m "feat: load accepted classifier artifacts"
```

### Task 4: `evaluate-classifier` CLI orchestration

**Files:**
- Create: `src/ai_digest/classifiers/service.py`
- Modify: `src/ai_digest/cli.py`
- Modify: `tests/test_cli.py`
- Create: `tests/test_classifier_service.py`

**Interfaces:**
- Consumes: dataset/category/split/report/model/manifest paths and an aware clock.
- Produces: `ClassifierEvaluationService.run() -> EvaluationResult` and injected CLI `evaluation_service_factory`.

- [ ] **Step 1: Write failing service orchestration tests**

Inject fakes for dataset loading, split creation, evaluation, report writing, and accepted-model saving. Assert call order; report persistence on failure; no model save below baseline; and model save only after a passing report.

```python
result = service.run()
assert events == ["load", "cohort", "split", "evaluate", "report", "model"]
assert result.beats_baseline is True
```

- [ ] **Step 2: Run the focused service test and confirm failure**

Run: `python -m pytest tests/test_classifier_service.py -v`

Expected: FAIL because the service is missing.

- [ ] **Step 3: Implement service defaults and split verification**

Use repository-relative defaults `data/classifier/training.csv`, `data/classifier/split.json`, `data/classifier/evaluation.json`, `models/classifier.joblib`, and `models/classifier-manifest.json`. Reuse an existing split only when its dataset hash, seed, IDs, and counts exactly match; otherwise create and atomically write the deterministic split.

- [ ] **Step 4: Write failing CLI success/failure tests**

Extend `create_app` with an injected zero-argument evaluation service factory. Assert `evaluate-classifier` emits JSON containing `accuracy`, `macroF1`, `majorityBaselineAccuracy`, `beatsBaseline`, and artifact paths; below-baseline and validation errors must exit 1 with `DigestError.as_dict()` on stderr.

- [ ] **Step 5: Implement the CLI command without constructing provider clients**

```python
@application.command("evaluate-classifier")
def evaluate_classifier() -> None:
    try:
        result = evaluation_service_factory().run()
        _emit(result.cli_payload())
    except DigestError as error:
        report_error(error)
```

Give `evaluation_service_factory` a local default so existing test call sites remain compatible; `_evaluation_service()` must not read Gemini/OpenAI keys.

- [ ] **Step 6: Run focused and regression tests, then commit**

Run: `python -m pytest tests/test_classifier_service.py tests/test_cli.py -v`

Expected: all selected tests PASS, including key-free local commands.

Commit:

```powershell
git add src/ai_digest/classifiers/service.py src/ai_digest/cli.py tests/test_classifier_service.py tests/test_cli.py
git commit -m "feat: add classifier evaluation command"
```

### Task 5: Production classifier composition

**Files:**
- Modify: `src/ai_digest/cli.py`
- Modify: `scripts/publish_url.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_publish_url_script.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `TrainedClassifier(Path("models/classifier.joblib"), Path("models/classifier-manifest.json"), categories)`.
- Produces: `_classifier() -> Classifier`, used by both normal `add` and one-command publishing.

- [ ] **Step 1: Write failing composition tests**

Patch `cli.TrainedClassifier` and assert `_workflow()` passes `_classifier()` into `AddArticleWorkflow`. Update publisher tests to assert it calls `cli._classifier()` and never references `FixedClassifier`. Assert missing artifacts surface `MODEL_NOT_FOUND` before extraction/summarization and do not save a summary.

- [ ] **Step 2: Run tests and confirm the fixed-classifier expectations fail**

Run: `python -m pytest tests/test_cli.py tests/test_publish_url_script.py -v`

Expected: FAIL because both production composition points still construct `FixedClassifier`.

- [ ] **Step 3: Replace both production composition points**

```python
def _classifier() -> Classifier:
    return TrainedClassifier(
        Path("models/classifier.joblib"),
        Path("models/classifier-manifest.json"),
        tuple(json.loads(Path("data/categories.json").read_text(encoding="utf-8"))),
    )
```

Use `classifier=cli._classifier()` in `scripts/publish_url.py`. Keep `FixedClassifier` unchanged for explicit tests/local fixtures only; add no environment switch and no fallback.

- [ ] **Step 4: Document evaluation and runtime failure behavior**

Add PowerShell examples for dependency installation, `ai-digest evaluate-classifier`, artifact paths, review-state requirements, and the intentional `MODEL_NOT_FOUND` behavior before an accepted model exists. Do not include credentials or claim the classifier has passed before real evaluation.

- [ ] **Step 5: Run focused and full Python tests, then commit**

Run: `python -m pytest tests/test_cli.py tests/test_publish_url_script.py tests/test_workflow.py -v`

Run: `python -m pytest`

Expected: all Python tests PASS.

Commit:

```powershell
git add src/ai_digest/cli.py scripts/publish_url.py tests/test_cli.py tests/test_publish_url_script.py README.md
git commit -m "feat: use trained classifier in production"
```

### Task 6: Curate and review batch 1

**Files:**
- Create: `data/classifier/training.csv`
- Create: `docs/classifier-review.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: 60 manually inspected, directly readable public article URLs.
- Produces: batch 1 with ten `pending` rows per category and a reviewer procedure that edits only `reviewStatus`/`reviewNote` or appends a replacement row with a new ID.

- [ ] **Step 1: Research ten unambiguous sources per category**

Open each page individually, confirm HTTP(S), public direct readability, article title, and dominant subject. Exclude login/paywall/anti-bot pages, list pages, duplicate canonical URLs, ambiguous classifications, and pages lacking enough readable content. Record no cookies, tokens, page dumps, or substantial verbatim passages.

- [ ] **Step 2: Add 60 pending review rows**

Use IDs `b1-ai-001` through `b1-life-010`, `batch=1`, Traditional Chinese paraphrases in `text`, one exact category, original `sourceUrl`/`sourceTitle`, concise `rationale`, `reviewStatus=pending`, and blank `reviewNote`. Each category must have exactly ten rows.

- [ ] **Step 3: Add the reviewer guide**

Document these decisions exactly:

```text
approved：來源可直接讀取、內容轉述正確、主分類明確。
rejected：保留原列並在 reviewNote 說明原因，不進入訓練。
修訂：保留退件列，另以新 id 新增 pending 替代列。
```

Include commands that count rows/status/category with `load_dataset`; do not instruct reviewers to run final cohort validation until all 180 approvals exist.

- [ ] **Step 4: Validate offline structure and manually spot-check all URLs**

Run: `python -c "import json; from pathlib import Path; from ai_digest.classifiers.dataset import load_dataset; categories=tuple(json.loads(Path('data/categories.json').read_text(encoding='utf-8'))); rows=load_dataset(Path('data/classifier/training.csv'), categories); assert len(rows)==60; assert all(r.batch==1 and r.review_status=='pending' for r in rows); print('batch 1:', len(rows))"`

Expected: `batch 1: 60`.

Run the tracked/dist secret scanner before commit; expected exit code is 0. Record the research date and any unavailable candidates in `progress.md`, but do not mark the classifier dataset item complete.

- [ ] **Step 5: Commit the reviewable batch**

```powershell
git add data/classifier/training.csv docs/classifier-review.md progress.md todo.md
git commit -m "data: add classifier review batch one"
```

- [ ] **Step 6: Pause for user review**

Present the 60 rows grouped by category with ID, title, URL, paraphrased text, and rationale. Do not convert any row to `approved` until the user explicitly approves it; apply requested rejections/replacements as a separate data-only commit.

### Task 7: Complete the reviewed 180-example cohort

**Files:**
- Modify: `data/classifier/training.csv`
- Modify: `docs/classifier-review.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: explicit user decisions on batch 1, then two more independently researched 60-row batches.
- Produces: exactly 180 approved rows, 30 per category, with rejected history retained.

- [ ] **Step 1: Apply batch 1 review decisions without rewriting history**

Change only `reviewStatus` and `reviewNote` on reviewed rows. For every rejected row, append a new unique batch-1 replacement row and return it for review. Repeat until batch 1 contains exactly 60 approved rows, ten per category.

- [ ] **Step 2: Research and submit batch 2**

Add IDs prefixed `b2-`, ten new public directly readable sources per category, all initially `pending`. Validate CSV structure and present the same grouped review view. Apply user decisions until batch 2 has exactly 60 approved rows.

- [ ] **Step 3: Research and submit batch 3**

Add IDs prefixed `b3-`, ten new public directly readable sources per category, all initially `pending`. Validate CSV structure and present the same grouped review view. Apply user decisions until batch 3 has exactly 60 approved rows.

- [ ] **Step 4: Validate the final cohort and hash**

Run:

```powershell
python -c "import json; from pathlib import Path; from ai_digest.classifiers.dataset import load_dataset,approved_cohort,dataset_sha256; categories=tuple(json.loads(Path('data/categories.json').read_text(encoding='utf-8'))); rows=load_dataset(Path('data/classifier/training.csv'), categories); cohort=approved_cohort(rows, categories, 30); print(len(cohort), dataset_sha256(cohort))"
```

Expected: `180` followed by a 64-character SHA-256 value.

- [ ] **Step 5: Update progress truthfully and commit each approved batch**

After each batch, record counts, research/review date, rejected-history count, and dataset hash. Mark the dataset todo item complete only after the final command succeeds.

```powershell
git add data/classifier/training.csv docs/classifier-review.md progress.md todo.md
git commit -m "data: approve classifier review batch two"
git commit -m "data: approve classifier review batch three"
```

Stage and commit only the files changed for the corresponding batch; never combine both commits in one staging operation.

### Task 8: Generate accepted artifacts and close the milestone

**Files:**
- Create: `data/classifier/split.json`
- Create: `data/classifier/evaluation.json`
- Create: `models/classifier.joblib`
- Create: `models/classifier-manifest.json`
- Modify: `progress.md`
- Modify: `todo.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the reviewed 180-example cohort and Tasks 1–5 implementation.
- Produces: reproducible evaluation evidence and the production model used by `add` and `scripts/publish_url.py`.

- [ ] **Step 1: Run the real fixed evaluation**

Run: `ai-digest evaluate-classifier`

Expected: exit 0; JSON reports 144 train, 36 test, six test examples per category, `beatsBaseline: true`, and `accuracy` strictly greater than `majorityBaselineAccuracy`. If it exits 1, preserve `evaluation.json`, audit source/labels, and return to user review; do not tune parameters or create a production model.

- [ ] **Step 2: Independently verify every artifact**

Run this read-only check after replacing the six representative strings only if the reviewed cohort uses materially different vocabulary:

```powershell
python -c "import json,sklearn; from datetime import datetime; from pathlib import Path; from ai_digest.classifiers.dataset import load_dataset,approved_cohort,dataset_sha256; from ai_digest.classifiers.trained import TrainedClassifier; categories=tuple(json.loads(Path('data/categories.json').read_text(encoding='utf-8'))); rows=approved_cohort(load_dataset(Path('data/classifier/training.csv'),categories),categories,30); split=json.loads(Path('data/classifier/split.json').read_text(encoding='utf-8')); report=json.loads(Path('data/classifier/evaluation.json').read_text(encoding='utf-8')); manifest=json.loads(Path('models/classifier-manifest.json').read_text(encoding='utf-8')); expected_hash=dataset_sha256(rows); assert split['datasetSha256']==report['datasetSha256']==manifest['datasetSha256']==expected_hash; assert split['seed']==manifest['seed']==42; assert tuple(manifest['categories'])==categories; assert manifest['trainingExamples']==180; assert manifest['scikitLearnVersion']==sklearn.__version__; assert datetime.fromisoformat(manifest['trainedAt']).utcoffset() is not None; train=set(split['trainIds']); test=set(split['testIds']); assert len(test)==36 and train.isdisjoint(test) and len(train|test)==180; classifier=TrainedClassifier(Path('models/classifier.joblib'),Path('models/classifier-manifest.json'),categories); texts=('生成式人工智慧模型與治理','Python 程式測試與除錯','晶片公司市場與科技政策','面試管理與職場策略','使用者體驗與視覺設計','自主學習與生活成長'); assert all(classifier.predict(text) in categories for text in texts); print('classifier artifacts verified')"
```

Expected: print `classifier artifacts verified` and exit 0.

- [ ] **Step 3: Run all repository gates**

Run:

```powershell
python -m pytest
npm.cmd test --prefix site
npm.cmd run check --prefix site
npm.cmd run build:pages --prefix site
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
```

Expected: all commands exit 0; Astro reports zero diagnostics; deployment verification reports no sensitive data or base-path violations.

- [ ] **Step 4: Record exact evaluation evidence**

In `progress.md`, record dataset/split hashes, Accuracy, Macro F1, majority baseline, strict comparison result, ordered confusion matrix, test counts, scikit-learn version, verification commands, and any residual risk. Check only the four formal-classifier todo items actually proven by the report.

- [ ] **Step 5: Commit the accepted milestone without pushing**

```powershell
git add data/classifier/split.json data/classifier/evaluation.json models/classifier.joblib models/classifier-manifest.json progress.md todo.md README.md
git diff --cached --check
git commit -m "feat: publish accepted classifier model"
```

Do not push, trigger GitHub Actions, or publish a new summary unless the user explicitly requests that separate external action.
