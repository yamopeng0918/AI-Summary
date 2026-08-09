# Public Web Milestone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested local flow that converts a public web article into a validated summary JSON file and renders published summaries in an Astro site.

**Architecture:** A Python package owns URL normalization, extraction, summarization contracts, classification boundaries, validation, storage, orchestration, and the CLI. The Astro application reads only validated JSON from `data/summaries`, generates list/detail pages, and performs client-side search, category filtering, and date sorting without accessing secrets.

**Tech Stack:** Python 3.14.6, Pydantic 2, Typer, HTTPX, Trafilatura, OpenAI Python SDK, pytest, Astro 5, TypeScript, Vitest, Node 24.18.0, npm 11.16.0.

## Global Constraints

- All user-visible generated summary text is Traditional Chinese.
- The first milestone supports only directly readable public web pages; YouTube and social sources remain separate plans.
- `keyPoints` contains 3–5 items, `tags` contains 1–5 normalized items, and `category` comes from the versioned category list.
- Dates use timezone-aware ISO 8601 values with `Asia/Taipei` as the default system timezone.
- Duplicate `canonicalUrl` values are rejected and archived records remain on disk.
- No credentials may enter Git, fixtures, summary JSON, frontend assets, build output, logs, or errors.
- No production function is written before its test has failed for the expected missing behavior.
- Existing untracked proposal documents and `build_project_proposal.py` are user files and must not be added to implementation commits unless the user explicitly requests it.

---

## File Structure

```text
pyproject.toml                         Python package, dependencies, pytest settings, CLI entry point
.gitignore                             Local environments, secrets, caches, models and build output
.env.example                           Secret variable names with empty values
src/ai_digest/domain.py               Summary, extraction and error value objects
src/ai_digest/url_normalizer.py       Public HTTP(S) URL canonicalization
src/ai_digest/storage.py              Schema-first JSON repository
src/ai_digest/extractors/web.py       HTTP retrieval and article extraction
src/ai_digest/summarizers/base.py     Summarizer protocol
src/ai_digest/summarizers/openai.py   OpenAI structured-output adapter
src/ai_digest/classifiers/base.py     Classifier protocol
src/ai_digest/classifiers/fixed.py    Explicit development-only classifier
src/ai_digest/workflow.py             Add-article orchestration
src/ai_digest/cli.py                  Typer commands
data/categories.json                  Versioned initial category list
data/summaries/example.json           Valid published example used by the site
schemas/summary-v1.json               Portable JSON Schema
tests/fixtures/article.html           Stable local extraction fixture
tests/test_domain.py                  Domain validation tests
tests/test_url_normalizer.py          URL normalization tests
tests/test_storage.py                 Atomic persistence and duplicate tests
tests/test_web_extractor.py           Local fixture extraction tests
tests/test_openai_summarizer.py       Structured-output adapter tests
tests/test_workflow.py                End-to-end local pipeline tests
tests/test_cli.py                     CLI behavior tests
site/package.json                     Astro scripts and dependencies
site/astro.config.mjs                 Static build configuration
site/tsconfig.json                    Astro TypeScript settings
site/src/lib/summaries.ts             JSON loading, validation and filtering
site/src/lib/summaries.test.ts        Site data behavior tests
site/src/layouts/BaseLayout.astro     Shared metadata and responsive shell
site/src/pages/index.astro            List/search/filter/sort page
site/src/pages/summaries/[id].astro   Static detail pages
site/src/styles/global.css            Responsive visual styles
README.md                              Local setup and milestone commands
progress.md                            Evidence-based status and handoff
todo.md                                Updated MVP checklist
```

## Task 1: Project Foundation and Domain Contract

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/ai_digest/__init__.py`
- Create: `src/ai_digest/domain.py`
- Create: `schemas/summary-v1.json`
- Create: `data/categories.json`
- Test: `tests/test_domain.py`

**Interfaces:**
- Consumes: The summary fields and validation rules in the approved design.
- Produces: `SummaryRecord`, `ExtractedArticle`, `SummaryDraft`, and `DigestError`; later tasks import these exact names.

- [ ] **Step 1: Add packaging and safety configuration**

Create `pyproject.toml` with package name `ai-digest`, Python requirement `>=3.12`, runtime dependencies `pydantic>=2.11,<3`, `typer>=0.16,<1`, `httpx>=0.28,<1`, `trafilatura>=2,<3`, and `openai>=1.99,<3`; add `pytest>=8.4,<10` under the `dev` extra, map packages from `src`, and register `ai-digest = "ai_digest.cli:app"`. Configure pytest with `testpaths = ["tests"]` and `addopts = "-ra --strict-markers"`.

Create `.gitignore` containing `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.coverage`, `htmlcov/`, `models/`, `site/node_modules/`, `site/dist/`, and `.astro/`. Create `.env.example` containing only `OPENAI_API_KEY=` and `OPENAI_MODEL=gpt-5-mini`.

- [ ] **Step 2: Install the Python package**

Run: `python -m pip install -e ".[dev]"`

Expected: installation completes and `python -m pytest --version` prints pytest 8.x or 9.x.

- [ ] **Step 3: Write failing domain tests**

Create tests that instantiate `SummaryRecord` with the approved example and assert: valid input succeeds; two key points fail; six tags fail; blank tags fail; an unknown category fails; naive timestamps fail; and tags `[' OpenAI ', 'openai', 'AI']` normalize to `['OpenAI', 'AI']`. Load categories from `data/categories.json` and use the initial exact values `人工智慧`, `程式開發`, `科技產業`, `商業與職場`, `設計與創意`, and `生活與學習`.

Run: `python -m pytest tests/test_domain.py -v`

Expected: FAIL during import because `ai_digest.domain` does not exist.

- [ ] **Step 4: Implement the domain models minimally**

Implement Pydantic models with these fields and signatures:

```python
class ExtractedArticle(BaseModel):
    canonical_url: HttpUrl
    title: str
    author: str | None = None
    published_at: datetime | None = None
    text: str

class SummaryDraft(BaseModel):
    summary: str
    key_points: list[str] = Field(alias="keyPoints", min_length=3, max_length=5)
    tags: list[str] = Field(min_length=1, max_length=5)
    editorial: str

class SummaryRecord(BaseModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    id: str
    canonical_url: HttpUrl = Field(alias="canonicalUrl")
    source_type: Literal["web"] = Field(alias="sourceType")
    title: str
    author: str | None
    source_published_at: datetime | None = Field(alias="sourcePublishedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    summary: str
    key_points: list[str] = Field(alias="keyPoints", min_length=3, max_length=5)
    category: str
    tags: list[str] = Field(min_length=1, max_length=5)
    editorial: str
    status: Literal["published", "archived"]

class DigestError(Exception):
    def __init__(self, stage: str, code: str, message: str, retryable: bool) -> None: ...
    def as_dict(self) -> dict[str, str | bool]: ...
```

Use validators to reject blank strings, require timezone-aware timestamps, normalize tags while preserving the first spelling, and validate category membership against an injected or module-loaded immutable category set. Configure camelCase aliases and JSON serialization.

Generate `schemas/summary-v1.json` from `SummaryRecord.model_json_schema(by_alias=True)` and verify it describes the same required fields. Do not manually create a divergent schema.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_domain.py -v`

Expected: PASS.

Run: `git diff --check`

Expected: no output.

Commit: `git add pyproject.toml .gitignore .env.example src/ai_digest tests/test_domain.py schemas/summary-v1.json data/categories.json && git commit -m "feat: define summary domain contract"`

## Task 2: URL Normalization and Atomic Storage

**Files:**
- Create: `src/ai_digest/url_normalizer.py`
- Create: `src/ai_digest/storage.py`
- Test: `tests/test_url_normalizer.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `SummaryRecord` and `DigestError` from Task 1.
- Produces: `normalize_public_url(raw_url: str) -> str` and `SummaryRepository(root: Path)` with `save`, `list`, `get`, and `set_status` methods.

- [ ] **Step 1: Write and run failing URL tests**

Test that `HTTPS://Example.COM:443/path/?utm_source=x&b=2&a=1#part` becomes `https://example.com/path?a=1&b=2`; default HTTP port is removed; tracking parameters beginning with `utm_` plus `fbclid` and `gclid` are removed; fragments are removed; non-HTTP schemes, credentials in URLs, localhost, loopback, private, link-local, multicast, and unspecified IP literals raise `DigestError(stage="input", code="INVALID_URL", retryable=False)`.

Run: `python -m pytest tests/test_url_normalizer.py -v`

Expected: FAIL because `normalize_public_url` is missing.

- [ ] **Step 2: Implement URL normalization**

Implement `normalize_public_url(raw_url: str) -> str` with `urllib.parse`, `ipaddress`, lowercase IDNA hostnames, normalized ports and paths, sorted retained query pairs, and the exact safety exclusions from the test. Domain DNS resolution is not performed here; network destination validation is repeated by the extractor before connecting.

- [ ] **Step 3: Write and run failing repository tests**

Use `tmp_path` to assert `save(record)` writes UTF-8 JSON using aliases, refuses a second record with the same canonical URL even when IDs differ, leaves no temporary file after success, returns sorted records from `list()`, returns one record from `get(id)`, and changes only `status` and `updatedAt` through `set_status(id, status, now)`.

Run: `python -m pytest tests/test_storage.py -v`

Expected: FAIL because `SummaryRepository` is missing.

- [ ] **Step 4: Implement atomic repository behavior**

Implement:

```python
class SummaryRepository:
    def __init__(self, root: Path) -> None: ...
    def save(self, record: SummaryRecord) -> Path: ...
    def list(self) -> list[SummaryRecord]: ...
    def get(self, record_id: str) -> SummaryRecord: ...
    def set_status(self, record_id: str, status: Literal["published", "archived"], now: datetime) -> SummaryRecord: ...
```

Write JSON to a sibling `.tmp` file, flush and close it, then replace the destination atomically. Before saving, parse every existing JSON and compare canonical URLs. Convert duplicate, missing-record, invalid-existing-data, and write failures into stable `DigestError` values without including file content or credentials.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_url_normalizer.py tests/test_storage.py -v`

Expected: PASS.

Run: `python -m pytest && git diff --check`

Expected: all tests pass and diff check is silent.

Commit: `git add src/ai_digest/url_normalizer.py src/ai_digest/storage.py tests/test_url_normalizer.py tests/test_storage.py && git commit -m "feat: add safe URL and summary storage"`

## Task 3: Public Web Extraction

**Files:**
- Create: `src/ai_digest/extractors/__init__.py`
- Create: `src/ai_digest/extractors/web.py`
- Create: `tests/fixtures/article.html`
- Test: `tests/test_web_extractor.py`

**Interfaces:**
- Consumes: normalized public URL and `DigestError`.
- Produces: `WebExtractor(client: httpx.Client).extract(url: str) -> ExtractedArticle`.

- [ ] **Step 1: Add a representative local fixture and failing extraction tests**

The fixture contains a title, author meta tag, published-time meta tag, navigation, advertisement, and an article with three paragraphs totaling more than 200 characters. Tests use `httpx.MockTransport`, never external networking, and assert metadata extraction, article-only text, redirect rejection to a private address, non-HTML content rejection, HTTP failure mapping, and rejection when extracted text is shorter than 200 characters.

Run: `python -m pytest tests/test_web_extractor.py -v`

Expected: FAIL because `WebExtractor` is missing.

- [ ] **Step 2: Implement retrieval and extraction**

Implement a 15-second timeout, a project-specific User-Agent, a 2 MiB response limit, at most three redirects handled manually, and destination validation before every request. Accept only `text/html` and `application/xhtml+xml`. Use Trafilatura for main text and metadata, then return `ExtractedArticle`. Map timeouts and 429/5xx responses to retryable extraction errors; map login walls, other 4xx responses, invalid content type, oversized responses, and insufficient text to non-retryable errors.

- [ ] **Step 3: Verify and commit**

Run: `python -m pytest tests/test_web_extractor.py -v`

Expected: PASS with no real HTTP requests.

Run: `python -m pytest && git diff --check`

Expected: all tests pass and diff check is silent.

Commit: `git add src/ai_digest/extractors tests/fixtures/article.html tests/test_web_extractor.py && git commit -m "feat: extract public web articles"`

## Task 4: Summary, Classification Boundaries, and Workflow

**Files:**
- Create: `src/ai_digest/summarizers/__init__.py`
- Create: `src/ai_digest/summarizers/base.py`
- Create: `src/ai_digest/summarizers/openai.py`
- Create: `src/ai_digest/classifiers/__init__.py`
- Create: `src/ai_digest/classifiers/base.py`
- Create: `src/ai_digest/classifiers/fixed.py`
- Create: `src/ai_digest/workflow.py`
- Test: `tests/test_openai_summarizer.py`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Consumes: `ExtractedArticle`, `SummaryDraft`, `SummaryRecord`, `WebExtractor`, `SummaryRepository`.
- Produces: `Summarizer.summarize(article)`, `Classifier.predict(text)`, and `AddArticleWorkflow.run(url, now) -> SummaryRecord`.

- [ ] **Step 1: Write failing summarizer contract tests**

Define protocols:

```python
class Summarizer(Protocol):
    def summarize(self, article: ExtractedArticle) -> SummaryDraft: ...

class Classifier(Protocol):
    def predict(self, text: str) -> str: ...
```

Test the OpenAI adapter with an injected fake client whose parsed response returns a valid `SummaryDraft`; assert the system instruction requires Traditional Chinese, 3–5 key points, 1–5 tags, and no unsupported factual additions. Test refusal, missing parsed content, timeout, and malformed output mappings without making a real API call.

Run: `python -m pytest tests/test_openai_summarizer.py -v`

Expected: FAIL because the adapter is missing.

- [ ] **Step 2: Implement the OpenAI adapter**

Implement `OpenAISummarizer(client: OpenAI, model: str)` using the SDK structured response mechanism and `SummaryDraft` as the parsed schema. Catch only known SDK request, rate-limit, timeout, refusal, and validation failures; convert them to `DigestError(stage="summarize", ...)`. Never include prompts, source text, headers, or credentials in errors.

- [ ] **Step 3: Write failing workflow tests**

Use small real fakes implementing the protocols to assert this exact order: normalize, duplicate preflight, extract, summarize, classify, assemble, validate, save. Assert the record ID is deterministic from Taipei date plus a slug and a short canonical-URL hash; timestamps equal the injected aware `now`; classifier input combines title, summary, and key points; an invalid category fails at `classify`; any upstream error leaves the repository empty.

Run: `python -m pytest tests/test_workflow.py -v`

Expected: FAIL because `AddArticleWorkflow` is missing.

- [ ] **Step 4: Implement the development classifier and workflow**

Implement `FixedClassifier(category: str)` as an explicitly development-only adapter that validates its configured category. Implement:

```python
class AddArticleWorkflow:
    def __init__(self, extractor: WebExtractor, summarizer: Summarizer,
                 classifier: Classifier, repository: SummaryRepository) -> None: ...
    def run(self, raw_url: str, now: datetime) -> SummaryRecord: ...
```

The workflow creates a `published` web record, preserves extracted metadata, normalizes tags through the domain model, and saves only after complete validation. It does not deploy or modify the website.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_openai_summarizer.py tests/test_workflow.py -v`

Expected: PASS.

Run: `python -m pytest && git diff --check`

Expected: all tests pass and diff check is silent.

Commit: `git add src/ai_digest/summarizers src/ai_digest/classifiers src/ai_digest/workflow.py tests/test_openai_summarizer.py tests/test_workflow.py && git commit -m "feat: orchestrate article summarization"`

## Task 5: CLI Commands

**Files:**
- Create: `src/ai_digest/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `AddArticleWorkflow` and `SummaryRepository`.
- Produces: Typer `app` with `add`, `list`, `show`, `archive`, and `publish` commands.

- [ ] **Step 1: Write failing CLI tests**

Use Typer `CliRunner` and an injected application factory. Test that `add URL` prints the six stage names and final ID/path, domain failures print the public error message to stderr and return exit code 1, `list` prints ID/title/category/status, `show ID` emits valid JSON, and archive/publish change status while preserving content.

Run: `python -m pytest tests/test_cli.py -v`

Expected: FAIL because `ai_digest.cli` is missing.

- [ ] **Step 2: Implement the minimal CLI**

Implement `create_app(workflow_factory, repository_factory, clock) -> typer.Typer` for tests and expose production `app`. Load `.env` only through process environment access; require `OPENAI_API_KEY` only for `add`, never for local list/show/status commands. Default repository root is `data/summaries`. Emit structured stage progress and catch only `DigestError` at the command boundary.

- [ ] **Step 3: Verify and commit**

Run: `python -m pytest tests/test_cli.py -v`

Expected: PASS.

Run: `python -m pytest && ai-digest --help && git diff --check`

Expected: tests pass, help lists the five commands, and diff check is silent.

Commit: `git add src/ai_digest/cli.py tests/test_cli.py && git commit -m "feat: add local digest CLI"`

## Task 6: Astro Summary Website

**Files:**
- Create: `site/package.json`
- Create: `site/astro.config.mjs`
- Create: `site/tsconfig.json`
- Create: `site/src/lib/summaries.ts`
- Create: `site/src/lib/summaries.test.ts`
- Create: `site/src/layouts/BaseLayout.astro`
- Create: `site/src/pages/index.astro`
- Create: `site/src/pages/summaries/[id].astro`
- Create: `site/src/styles/global.css`
- Create: `data/summaries/example.json`

**Interfaces:**
- Consumes: validated summary JSON using the Task 1 aliases.
- Produces: static list and detail pages plus client-side `filterAndSortSummaries(records, query, category, order)`.

- [ ] **Step 1: Add the site configuration and install dependencies**

Create scripts `test: vitest run`, `build: astro check && astro build`, and `dev: astro dev`. Add Astro 5, TypeScript 5, Vitest 3, `@astrojs/check`, and `zod` dependencies, with Node engine `>=22`. Configure Astro for static output and `srcDir: './src'`.

Run from `site`: `npm.cmd install`

Expected: `package-lock.json` is created with no install error.

- [ ] **Step 2: Write failing data behavior tests**

Test that the loader rejects invalid key-point counts, excludes archived records, sorts newest first by default, sorts oldest on request, filters one category, searches title/summary/key points case-insensitively, and returns an empty array for no match. Use in-memory objects, not generated HTML snapshots.

Run from `site`: `npm.cmd test`

Expected: FAIL because `src/lib/summaries.ts` is missing.

- [ ] **Step 3: Implement validated loading and filtering**

Define a Zod schema matching `summary-v1.json` and export its inferred `SummaryRecord` type. At build time, use read-only Node `fs` APIs to load `../../../data/summaries/*.json` relative to `site/src/lib/summaries.ts`, parse every file, filter `published`, and implement:

```ts
export function filterAndSortSummaries(
  records: SummaryRecord[],
  query: string,
  category: string,
  order: 'newest' | 'oldest'
): SummaryRecord[]
```

Search over title, summary, and joined key points using trimmed locale-lowercase text. Do not fetch data from a runtime API.

- [ ] **Step 4: Create pages and responsive presentation**

Create a semantic base layout, an index page with a text input, category select, order select, summary cards, no-data state, and no-results state, plus static detail pages from `getStaticPaths()`. Client-side code calls the tested filter function and updates existing cards without injecting untrusted HTML. Detail pages show every approved field and use `rel="noopener noreferrer"` on the source link.

Create `example.json` with a clearly labeled fictional `https://example.com/ai-digest-demo` source, three key points, category `人工智慧`, 1–5 tags, aware timestamps, and `published` status.

- [ ] **Step 5: Verify and commit**

Run from `site`: `npm.cmd test`

Expected: PASS.

Run from `site`: `npm.cmd run build`

Expected: Astro type checking and static build pass; output includes index and example detail pages.

Run from repository root: `git diff --check`

Expected: no output.

Commit: `git add site data/summaries/example.json && git commit -m "feat: render published summaries"`

## Task 7: Milestone Integration, Documentation, and Safety Check

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`
- Create: `tests/test_local_pipeline.py`

**Interfaces:**
- Consumes: all first-milestone components.
- Produces: reproducible setup instructions and a tested local fixture-to-JSON workflow.

- [ ] **Step 1: Write the failing local integration test**

Build the real `WebExtractor` with `httpx.MockTransport` serving `tests/fixtures/article.html`, a deterministic summarizer implementing `Summarizer`, a `FixedClassifier("人工智慧")`, and `SummaryRepository(tmp_path)`. Assert `AddArticleWorkflow.run()` produces one schema-valid published JSON record and a second call with the same URL raises the duplicate error without adding a file.

Run: `python -m pytest tests/test_local_pipeline.py -v`

Expected: PASS if the earlier TDD cycles already established every component boundary. This is an integration verification test over already tested production behavior, so it does not need to be forced red. If it fails, confirm the failure identifies a real cross-component mismatch before changing production code.

- [ ] **Step 2: Make only the wiring changes required by the integration test**

Add no new product behavior. If Step 1 fails, first add the smallest failing unit or orchestration test that isolates the missing behavior, confirm that focused test fails for the expected reason, then correct dependency construction, serialization, or protocol mismatches and rerun both tests until they pass.

- [ ] **Step 3: Update project documentation**

Write `README.md` with Windows PowerShell commands for creating `.venv`, installing `.[dev]`, setting `OPENAI_API_KEY` in the current process, running tests, using each implemented CLI command, installing site dependencies, running the site, and producing a static build. Document that the fixed classifier is development-only and that real classifier evaluation, YouTube, social sources, and deployment are later milestones.

Revise `progress.md` and `todo.md` to use the approved three-source MVP, move PDF/OCR to optional work, add the classifier baseline requirement, and mark only work demonstrated by passing commands. Preserve historical entries while adding a 2026-08-09 entry.

- [ ] **Step 4: Run full verification**

Run from repository root: `python -m pytest`

Expected: all Python tests pass without warnings.

Run from `site`: `npm.cmd test`

Expected: all Vitest tests pass.

Run from `site`: `npm.cmd run build`

Expected: Astro check and build pass.

Run from repository root: `git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|OPENAI_API_KEY=.+)" -- . ':!docs/superpowers/plans/*'`

Expected: no output.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Perform one real-source acceptance when credentials are available**

After the user supplies and approves a directly readable public article URL, assign it without committing the value:

```powershell
$env:AI_DIGEST_ACCEPTANCE_URL = 'https://the-user-approved-host.example/the-approved-path'
ai-digest add $env:AI_DIGEST_ACCEPTANCE_URL
```

Expected: the CLI reports all stages, writes one valid JSON file, and does not expose the key. Then run `npm.cmd run build` in `site` and confirm the new detail page appears in `site/dist`.

If no user-approved URL or OpenAI credential is available, record this item as unverified in `progress.md`; do not substitute an arbitrary external target or claim the real-source criterion passed.

- [ ] **Step 6: Commit the verified milestone**

Run: `git status --short`

Expected: only README, progress, todo, the integration test, and any strictly required wiring fixes are staged; original proposal files remain untracked unless separately authorized.

Commit: `git add README.md progress.md todo.md tests/test_local_pipeline.py src/ai_digest && git commit -m "docs: complete public web milestone handoff"`

## Plan Self-Review Results

- Spec coverage: the plan covers the complete first milestone—domain validation, safe public URL handling, extraction, structured summary boundary, temporary classification boundary, atomic storage, CLI, Astro list/detail/search/filter/sort, integration, documentation, and security verification.
- Deliberate exclusions: trained classifier evaluation, YouTube, social sources, remote GitHub configuration, Pages deployment, PDF, OCR, and tag filtering remain separate milestones as required by the approved design.
- Type consistency: Python domain names, protocol signatures, JSON aliases, repository methods, and TypeScript field names are consistent across tasks.
- Placeholder scan: the plan contains no implementation placeholders; the only runtime-dependent acceptance input is explicitly gated on a user-approved public URL and locally available credential.
