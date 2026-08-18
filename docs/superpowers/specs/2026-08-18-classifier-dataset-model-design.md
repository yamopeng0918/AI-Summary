# Classifier Dataset and Model Design

## Goal and scope

Replace the development-only fixed classifier with a reproducible Traditional
Chinese article classifier that is trained on reviewed, source-grounded data and
whose held-out Accuracy is strictly greater than the majority-class baseline.

This milestone covers the six existing mutually exclusive categories, dataset
curation and review, TF-IDF plus Logistic Regression training, evaluation,
versioned artifacts, CLI integration, and production prediction. It does not add
YouTube, social sources, PDF, OCR, multi-label classification, online training,
deep learning, vector databases, or automatic hyperparameter search.

## Categories and annotation rules

The category list remains owned by `data/categories.json`:

- `人工智慧`: AI models, generative AI, machine-learning applications, and AI
  governance whose main subject is the technology.
- `程式開發`: programming languages, frameworks, software engineering,
  implementation, testing, and debugging.
- `科技產業`: technology companies, products, markets, industry policy, and
  ecosystem analysis.
- `商業與職場`: management, job seeking, interviews, business strategy, and
  workplace methods.
- `設計與創意`: visual design, UX, creative practice, and content design.
- `生活與學習`: self-directed learning, personal growth, life skills, and
  education not primarily about workplace practice.

Annotators choose the article's primary purpose, intended reader action, and
dominant subject. Ambiguous candidates are excluded rather than forced into a
category.

## Dataset construction

The initial approved training cohort contains exactly 180 examples: 30 examples
per category. Every approved example is grounded in a different directly
readable public article. The training text is a Traditional Chinese paraphrase
of the title and main ideas; it does not reproduce substantial source passages.

`data/classifier/training.csv` uses these columns:

- `id`: immutable unique example identifier.
- `batch`: review batch `1`, `2`, or `3`.
- `text`: source-grounded Traditional Chinese classification input.
- `label`: one exact configured category.
- `sourceUrl`: unique public HTTP(S) source URL.
- `sourceTitle`: source article title.
- `rationale`: concise explanation for the label.
- `reviewStatus`: `pending`, `approved`, or `rejected`.
- `reviewNote`: optional reviewer feedback.

The approved cohort is delivered in three batches of 60 examples. Rejected
examples stay in the CSV as review history, so the file may contain more than 180
rows, but they never enter training. A revised example receives a new `id`; an
approved row is never silently rewritten. Only rows with
`reviewStatus=approved` are eligible for training or evaluation, and the final
approved cohort must still contain exactly 30 examples per category.

Source collection is deliberate research rather than an automated bulk crawler.
Every URL is checked as public and directly readable before inclusion.

## Split and leakage prevention

After all 180 examples are approved, the evaluator creates a stratified split
using random seed `42`: 24 training and 6 test examples per category, for 144
training and 36 test examples. Each source URL occurs once, so no source can cross
the train/test boundary.

The exact assignment is saved in `data/classifier/split.json`. Re-running against
the same approved dataset must reproduce the same assignment. Dataset validation
rejects duplicate IDs, duplicate canonical source URLs, missing fields, unknown
labels, invalid review states, non-public URLs, blank text, incorrect per-class
counts, or any unapproved row when final evaluation is requested.

## Model

The first model is a scikit-learn pipeline:

```python
TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))
LogisticRegression(max_iter=2000, random_state=42)
```

Character n-grams avoid a new Chinese tokenization dependency and are robust to
word-boundary variation. The MVP does not automatically tune parameters against
the held-out test set. If the model fails acceptance, the next action is to audit
labels and examples before considering a separately approved parameter change.

The classifier accepts plain text and returns one exact configured category. It
does not fetch sources, alter summaries, or save records.

## Evaluation and artifacts

`ai-digest evaluate-classifier` performs the following steps:

1. Validate the dataset and configured categories.
2. Create or verify the deterministic stratified split.
3. Fit the evaluation pipeline on the 144 training examples only.
4. Evaluate the untouched 36-example test set.
5. Save the report even when acceptance fails.
6. Require `accuracy > majorityBaselineAccuracy`.
7. On acceptance only, refit the production pipeline on all 180 approved examples
   and save the deployable model.

`data/classifier/evaluation.json` records:

- dataset and split SHA-256 values;
- seed and model parameters;
- training and test sample counts;
- per-category sample counts;
- Accuracy and Macro F1;
- precision, recall, F1, and support for every category;
- a confusion matrix using the exact `data/categories.json` order;
- majority-class baseline Accuracy;
- `beatsBaseline` and the overall acceptance result;
- Python and scikit-learn versions and an aware ISO 8601 evaluation timestamp.

Version-controlled outputs are:

- `data/classifier/training.csv`;
- `data/classifier/split.json`;
- `data/classifier/evaluation.json`;
- `models/classifier.joblib`;
- `models/classifier-manifest.json`.

The manifest stores the ordered categories, random seed, approved dataset hash,
model parameters, scikit-learn version, aware training timestamp, and number of
examples used for the production fit. Only the repository-controlled model
artifact is loaded; user-supplied pickle/joblib files are outside scope.

## Production integration

The existing `Classifier` protocol remains the workflow boundary. A trained-model
adapter loads and validates the model and manifest, then implements
`predict(text: str) -> str`.

Production `add` and `scripts/publish_url.py` composition use the trained model.
`FixedClassifier` remains available only for tests and explicit development
composition. There is no silent fallback. A missing model, incompatible artifact,
category-order mismatch, or prediction failure stops at the `classify` stage
before summary storage.

## Errors

Classifier failures use the existing structured `DigestError` shape with stage
`classify` and safe messages. Codes are:

- `INVALID_DATASET`;
- `UNAPPROVED_DATA`;
- `CATEGORY_MISMATCH`;
- `INSUFFICIENT_SAMPLES`;
- `MODEL_NOT_FOUND`;
- `MODEL_VERSION_MISMATCH`;
- `EVALUATION_BELOW_BASELINE`;
- `PREDICTION_FAILED`.

Errors do not expose source content, credentials, local environment values, or
untrusted serialized data. Failed evaluation never overwrites the last accepted
production model.

## Testing and completion gates

Implementation follows TDD. Automated tests use local fixtures and cover:

- CSV schema, duplicate IDs and URLs, category and review-state validation;
- exact per-class counts and approved-only eligibility;
- deterministic split assignment and hashes;
- reproducible metrics, majority baseline, classification report, and confusion
  matrix from a fixed small fixture;
- model save/load and manifest validation;
- missing model, incompatible version, category mismatch, and prediction errors;
- CLI success and below-baseline non-zero failure;
- production article creation using the trained-model adapter;
- preservation of the last accepted model after failed evaluation.

Daily tests require no network or paid API. Completion requires focused tests, the
full Python suite, frontend tests, Pages production build, tracked/dist sensitive
data verification, `git diff --check`, a checked-in evaluation report, recorded
Accuracy/Macro F1/confusion matrix/majority baseline, and proof that held-out
Accuracy is strictly greater than the baseline. The classifier milestone remains
incomplete until all 180 examples are reviewed and the acceptance condition is
met.
