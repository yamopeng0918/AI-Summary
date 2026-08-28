# Bluesky Social Post Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, test-driven ingestion of one public, non-reply Bluesky post through the existing AI Digest CLI, persistence, and GitHub Pages pipeline.

**Architecture:** Add local Bluesky URL parsing, a fixed-host AppView client, and an isolated `BlueskyExtractor` that returns the existing `ExtractedArticle` boundary. Route Bluesky independently from YouTube and generic web extraction, canonicalize saved posts to DID URLs, and extend the existing Python/JSON/TypeScript source-type contract to `social` without changing summarization or classification responsibilities.

**Tech Stack:** Python 3.12+, Pydantic 2, httpx 0.28, pytest 8.4+, JSON Schema, Astro 7, TypeScript 5.8, Zod 3, Vitest 3.

## Global Constraints

- Accept only `https://bsky.app/profile/<handle-or-did>/post/<post-id>`; strip query and fragment locally.
- Reject reply posts; do not expand quoted posts, parents, replies, or threads.
- Content consists only of the post text, author-provided image alt text, and embedded external-link title, in that order.
- Do not download images or embedded URLs, run OCR, generate image descriptions, scrape HTML, or use a Bluesky SDK.
- Use only the fixed public AppView host `https://public.api.bsky.app`; do not send credentials, cookies, or authorization headers.
- Persist the canonical URL as `https://bsky.app/profile/<did>/post/<post-id>` and reject duplicate canonical URLs before any paid summarization call.
- Keep extraction, summarization, classification, validation, and persistence responsibilities separate.
- All feature and behavior changes use red-green-refactor TDD; automated tests use fixtures or fake clients and require neither network access nor paid APIs.
- Preserve all unrelated user files and changes. Do not push, deploy, or make a paid API call without explicit user authorization at execution time.

---

## File Structure

- `src/ai_digest/source_urls.py`: recognize and locally normalize supported Bluesky post URLs.
- `src/ai_digest/extractors/bluesky.py`: fixed-host AppView transport, response validation, content mapping, and Bluesky extraction errors.
- `src/ai_digest/extractors/router.py`: route Bluesky independently between YouTube and generic web.
- `src/ai_digest/cli.py`: construct the production Bluesky extractor with the existing `httpx.Client` factory.
- `src/ai_digest/domain.py`: allow `social` in extracted and persisted domain models.
- `src/ai_digest/workflow.py`: repeat duplicate detection after extraction resolves a handle to its DID canonical URL.
- `schemas/summary-v1.json`: allow persisted `social` records.
- `site/src/lib/summaries.ts`: allow `social` in the frontend record type.
- `site/src/lib/summary-loader.ts`: validate `social` records at build time.
- `tests/fixtures/bluesky/post.json`: representative public AppView fixture with post text, image alt text, external card, and ignored quote data.
- `tests/test_bluesky_extractor.py`: extractor mapping, fixed-host transport, error, and security coverage.
- Existing focused test files cover contracts, URL parsing, routing, workflow duplicate prevention, CLI composition, and frontend validation.

### Task 1: Extend the shared source-type data contract

**Files:**
- Modify: `src/ai_digest/domain.py`
- Modify: `schemas/summary-v1.json`
- Modify: `site/src/lib/summaries.ts`
- Modify: `site/src/lib/summary-loader.ts`
- Modify: `tests/test_domain.py`
- Modify: `tests/test_storage.py`
- Modify: `site/src/lib/summaries.test.ts`

**Interfaces:**
- Consumes: existing `ExtractedArticle`, `SummaryRecord`, JSON Schema, `SummaryRecord` TypeScript interface, and `SummaryRecordSchema`.
- Produces: the exact shared source-type union `Literal["web", "youtube", "social"]`, JSON enum `['web', 'youtube', 'social']`, and TypeScript/Zod equivalent.

- [ ] **Step 1: Write failing Python contract tests**

Add tests that construct and serialize both domain objects with `sourceType="social"`, and validate a persisted social record through `SummaryRepository`:

```python
def test_summary_and_extracted_article_accept_social_source_type() -> None:
    article = ExtractedArticle(
        canonicalUrl="https://bsky.app/profile/did:plc:alice/post/3social",
        sourceType="social",
        title="Alice（@alice.example）的 Bluesky 貼文",
        author="Alice",
        publishedAt="2026-08-28T01:02:03Z",
        text="公開貼文",
    )
    record = valid_record(
        canonicalUrl="https://bsky.app/profile/did:plc:alice/post/3social",
        sourceType="social",
    )

    assert article.source_type == "social"
    assert record.source_type == "social"
```

- [ ] **Step 2: Write failing frontend contract tests**

Add a `social` record case to `site/src/lib/summaries.test.ts` and assert that `parseSummaryRecord` accepts it while the existing invalid-source test still rejects unknown values:

```ts
expect(parseSummaryRecord({
  ...validRecord,
  canonicalUrl: 'https://bsky.app/profile/did:plc:alice/post/3social',
  sourceType: 'social',
}).sourceType).toBe('social');
```

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain.py tests/test_storage.py -q
Set-Location site
npm.cmd test -- --run src/lib/summaries.test.ts
Set-Location ..
```

Expected: Python Pydantic and frontend Zod reject `social` because the current unions only contain `web` and `youtube`.

- [ ] **Step 4: Implement the minimal shared contract change**

Change both Pydantic fields to:

```python
source_type: Literal["web", "youtube", "social"]
```

Add `"social"` to `schemas/summary-v1.json`, change the frontend interface to:

```ts
sourceType: 'web' | 'youtube' | 'social';
```

and change the Zod field to:

```ts
sourceType: z.enum(['web', 'youtube', 'social']),
```

- [ ] **Step 5: Run focused contract verification**

Run the commands from Step 3 plus:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_domain.py tests/test_storage.py tests/test_workflow.py -q
```

Expected: all selected Python and Vitest tests pass.

- [ ] **Step 6: Commit the data contract**

```powershell
git add src/ai_digest/domain.py schemas/summary-v1.json site/src/lib/summaries.ts site/src/lib/summary-loader.ts tests/test_domain.py tests/test_storage.py site/src/lib/summaries.test.ts
git commit -m "feat: allow social summary sources"
```

### Task 2: Parse and normalize approved Bluesky post URLs

**Files:**
- Modify: `src/ai_digest/source_urls.py`
- Modify: `tests/test_source_urls.py`

**Interfaces:**
- Consumes: `normalize_public_url(raw_url: str) -> str` and existing YouTube canonicalization.
- Produces: `BlueskyPostRef(actor: str, post_id: str)`, `parse_bluesky_post_url(url: str) -> BlueskyPostRef`, and `is_bluesky_url(url: str) -> bool`.

- [ ] **Step 1: Write failing URL tests**

Cover handle, DID, query/fragment removal, strict host/path matching, missing identifiers, extra segments, credentials, ports, HTTP, and invalid input:

```python
@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "https://bsky.app/profile/alice.example/post/3social?ref=share#thread",
            "https://bsky.app/profile/alice.example/post/3social",
        ),
        (
            "https://bsky.app/profile/did:plc:alice/post/3social",
            "https://bsky.app/profile/did:plc:alice/post/3social",
        ),
    ],
)
def test_canonicalizes_supported_bluesky_post_urls(raw_url: str, expected: str) -> None:
    assert is_bluesky_url(raw_url) is True
    assert canonicalize_source_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url",
    [
        "http://bsky.app/profile/alice.example/post/3social",
        "https://bsky.app/profile/alice.example",
        "https://bsky.app/profile/alice.example/post",
        "https://bsky.app/profile/alice.example/post/3social/extra",
        "https://bsky.app.evil.example/profile/alice.example/post/3social",
        "https://user@bsky.app/profile/alice.example/post/3social",
        "https://bsky.app:444/profile/alice.example/post/3social",
    ],
)
def test_rejects_nonapproved_bluesky_urls(raw_url: str) -> None:
    with pytest.raises(DigestError) as raised:
        canonicalize_source_url(raw_url)
    assert raised.value.code == "INVALID_URL"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_source_urls.py -q
```

Expected: FAIL because Bluesky URLs currently fall through generic web normalization and the new helpers do not exist.

- [ ] **Step 3: Implement strict local parsing**

Add an immutable reference and strict parser:

```python
@dataclass(frozen=True)
class BlueskyPostRef:
    actor: str
    post_id: str


def parse_bluesky_post_url(url: str) -> BlueskyPostRef:
    parsed = urlsplit(normalize_public_url(url))
    parts = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "bsky.app"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or len(parts) != 5
        or parts[1] != "profile"
        or parts[3] != "post"
        or not parts[2]
        or not parts[4]
    ):
        raise DigestError("input", "INVALID_URL", "URL must identify one supported Bluesky post", False)
    return BlueskyPostRef(parts[2], parts[4])
```

Make `is_bluesky_url` return `False` on `DigestError`. In `canonicalize_source_url`, detect host `bsky.app`, parse it, and return `https://bsky.app/profile/{actor}/post/{post_id}` before the existing YouTube branch.

- [ ] **Step 4: Run URL and regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_source_urls.py tests/test_url_normalizer.py -q
```

Expected: all selected tests pass, including existing YouTube and generic web normalization.

- [ ] **Step 5: Commit URL support**

```powershell
git add src/ai_digest/source_urls.py tests/test_source_urls.py
git commit -m "feat: recognize Bluesky post URLs"
```

### Task 3: Build the fixed-host AppView client and Bluesky extractor

**Files:**
- Create: `src/ai_digest/extractors/bluesky.py`
- Create: `tests/test_bluesky_extractor.py`
- Create: `tests/fixtures/bluesky/post.json`

**Interfaces:**
- Consumes: `parse_bluesky_post_url(url) -> BlueskyPostRef`, `DigestError`, and `ExtractedArticle`.
- Produces: `BlueskyAppView` protocol, `BlueskyAppViewClient(client_factory: Callable[[], httpx.Client])`, and `BlueskyExtractor(appview: BlueskyAppView)`.

- [ ] **Step 1: Add the representative fixture and failing mapping test**

The fixture must include author DID/handle/display name, an aware `createdAt`, post text, duplicate/nonblank image alt values, an external-card title, a quote embed with text that must be ignored, and no `reply` field. Write a fake AppView test:

```python
class FakeAppView:
    def resolve_handle(self, handle: str) -> str:
        assert handle == "alice.example"
        return "did:plc:alice"

    def get_post(self, uri: str) -> dict[str, object]:
        assert uri == "at://did:plc:alice/app.bsky.feed.post/3social"
        return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_extracts_only_approved_bluesky_text() -> None:
    article = BlueskyExtractor(FakeAppView()).extract(
        "https://bsky.app/profile/alice.example/post/3social"
    )
    assert str(article.canonical_url) == "https://bsky.app/profile/did:plc:alice/post/3social"
    assert article.source_type == "social"
    assert article.title == "Alice（@alice.example）的 Bluesky 貼文"
    assert article.author == "Alice"
    assert article.published_at.isoformat() == "2026-08-28T01:02:03+00:00"
    assert article.text == "貼文：\n公開貼文 #AI\n\n圖片替代文字：\n架構圖\n\n外部連結標題：\nAI Digest 文件"
    assert "引用貼文不得出現" not in article.text
```

- [ ] **Step 2: Add failing boundary and error tests**

Use parametrized fake responses to cover DID input without `resolve_handle`, display-name fallback to handle, text-only, alt-only, external-title-only, deduplication, blank content, reply record, missing post, access denied, author-DID mismatch, malformed record, malformed timestamp, unexpected fake-client exception, and the exact error tuples from the spec.

```python
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (DigestError("extract", "POST_NOT_FOUND", "Bluesky post was not found", False), ("POST_NOT_FOUND", False)),
        (DigestError("extract", "SOURCE_ACCESS_DENIED", "Bluesky post is not publicly accessible", False), ("SOURCE_ACCESS_DENIED", False)),
        (TimeoutError(), ("UPSTREAM_UNAVAILABLE", True)),
    ],
)
def test_sanitizes_appview_failures(failure: Exception, expected: tuple[str, bool]) -> None:
    with pytest.raises(DigestError) as raised:
        BlueskyExtractor(FailingAppView(failure)).extract(BLUESKY_URL)
    assert (raised.value.code, raised.value.retryable) == expected
```

- [ ] **Step 3: Run extractor tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bluesky_extractor.py -q
```

Expected: collection fails because `ai_digest.extractors.bluesky` does not exist.

- [ ] **Step 4: Implement the extractor against the protocol**

Define the protocol and extractor boundary:

```python
class BlueskyAppView(Protocol):
    def resolve_handle(self, handle: str) -> str: ...
    def get_post(self, uri: str) -> dict[str, Any]: ...


class BlueskyExtractor:
    def __init__(self, appview: BlueskyAppView) -> None:
        self._appview = appview

    def extract(self, url: str) -> ExtractedArticle:
        ref = parse_bluesky_post_url(url)
        did = ref.actor if ref.actor.startswith("did:") else self._appview.resolve_handle(ref.actor)
        post = self._appview.get_post(f"at://{did}/app.bsky.feed.post/{ref.post_id}")
        return self._article(post, did, ref.post_id)
```

Implement `_article` with strict dict/string checks, author-DID equality, aware ISO 8601 parsing, reply rejection, and fixed labeled sections. Traverse only the current post's image-view `alt` values and external-view `title`; for record-with-media inspect only its current-post media embed and never its quoted record. Deduplicate equal nonblank supplemental strings while preserving order.

- [ ] **Step 5: Add failing HTTP transport tests**

Use `httpx.MockTransport` through a supplied client factory. Assert the exact requests are:

```text
GET https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=alice.example
GET https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?uris=at%3A%2F%2Fdid%3Aplc%3Aalice%2Fapp.bsky.feed.post%2F3social
```

Also assert there is no `Authorization` or `Cookie` header, no redirect following, no request to image/external embed URLs, bounded timeout, bounded response size, JSON content-type validation, and mappings for 400/401/403/404/429/5xx, timeout, invalid JSON, oversized response, and malformed response.

- [ ] **Step 6: Implement the fixed-host AppView client**

Use constants rather than injectable endpoints:

```python
_APPVIEW_ROOT = "https://public.api.bsky.app"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 15.0

class BlueskyAppViewClient:
    def __init__(self, client_factory: Callable[[], httpx.Client]) -> None:
        self._client_factory = client_factory

    def resolve_handle(self, handle: str) -> str:
        payload = self._get_json(
            "/xrpc/com.atproto.identity.resolveHandle", {"handle": handle}, author_lookup=True
        )
        # Validate and return payload["did"].

    def get_post(self, uri: str) -> dict[str, Any]:
        payload = self._get_json(
            "/xrpc/app.bsky.feed.getPosts", [("uris", uri)], author_lookup=False
        )
        # Require exactly one matching post and return it.
```

`_get_json` must build requests only from `_APPVIEW_ROOT` plus fixed XRPC paths, set `Accept: application/json` and the project User-Agent, omit credentials, set `follow_redirects=False`, stream and cap the body at 2 MiB, accept only JSON media types, and convert failures into the approved safe `DigestError` values without embedding response bodies.

- [ ] **Step 7: Run extractor tests and all existing extractor regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_bluesky_extractor.py tests/test_web_extractor.py tests/test_youtube_extractor.py tests/test_extractor_router.py -q
```

Expected: all selected tests pass with no external network requests.

- [ ] **Step 8: Commit the isolated extractor**

```powershell
git add src/ai_digest/extractors/bluesky.py tests/test_bluesky_extractor.py tests/fixtures/bluesky/post.json
git commit -m "feat: extract public Bluesky posts"
```

### Task 4: Route Bluesky and compose it in the production CLI

**Files:**
- Modify: `src/ai_digest/extractors/router.py`
- Modify: `src/ai_digest/cli.py`
- Modify: `tests/test_extractor_router.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `is_bluesky_url`, `BlueskyAppViewClient`, `BlueskyExtractor`, and existing `LazyExtractor`.
- Produces: `ExtractorRouter(web: Extractor, youtube: Extractor, bluesky: Extractor)` routing YouTube first, Bluesky second, and generic web last.

- [ ] **Step 1: Write failing router tests**

Update existing router construction to include a recording Bluesky extractor and add:

```python
def test_routes_bluesky_post_only_to_bluesky_extractor() -> None:
    web = RecordingExtractor(None)
    youtube = RecordingExtractor(None)
    bluesky = RecordingExtractor("social-result")
    router = ExtractorRouter(web=web, youtube=youtube, bluesky=bluesky)

    assert router.extract("https://bsky.app/profile/alice.example/post/3social") == "social-result"
    assert web.urls == []
    assert youtube.urls == []
    assert bluesky.urls == ["https://bsky.app/profile/alice.example/post/3social"]
```

- [ ] **Step 2: Write failing production-composition tests**

Monkeypatch `BlueskyAppViewClient` and `BlueskyExtractor`, call `cli._workflow()`, and assert the router contains a Bluesky extractor using `cli._web_client_factory`. Also assert selecting ordinary web or YouTube does not construct or call the AppView client.

- [ ] **Step 3: Run focused tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_extractor_router.py tests/test_cli.py -q
```

Expected: FAIL because the router has no Bluesky dependency and CLI does not compose one.

- [ ] **Step 4: Implement routing and CLI composition**

Change the router to:

```python
class ExtractorRouter:
    def __init__(self, web: Extractor, youtube: Extractor, bluesky: Extractor) -> None:
        self._web = web
        self._youtube = youtube
        self._bluesky = bluesky

    def extract(self, url: str) -> ExtractedArticle:
        if is_youtube_url(url):
            return self._youtube.extract(url)
        if is_bluesky_url(url):
            return self._bluesky.extract(url)
        return self._web.extract(url)
```

Import the Bluesky classes in `cli.py` and pass:

```python
BlueskyExtractor(BlueskyAppViewClient(client_factory=_web_client_factory))
```

as the third router dependency. No token or endpoint environment setting is added.

- [ ] **Step 5: Run routing, CLI, and extractor regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_extractor_router.py tests/test_cli.py tests/test_bluesky_extractor.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit production composition**

```powershell
git add src/ai_digest/extractors/router.py src/ai_digest/cli.py tests/test_extractor_router.py tests/test_cli.py
git commit -m "feat: route Bluesky posts through the CLI"
```

### Task 5: Prevent DID-alias duplicates before summarization

**Files:**
- Modify: `src/ai_digest/workflow.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_local_pipeline.py`

**Interfaces:**
- Consumes: extractor-resolved `article.canonical_url` and `SummaryRepository.list()`.
- Produces: a second canonical duplicate guard immediately after extraction and before `summarizer.summarize(article)`.

- [ ] **Step 1: Write a failing workflow test for handle/DID aliases**

Create an existing social record with a DID URL, submit the handle URL, let the fake extractor return the same DID URL, and assert no summarizer/classifier/save event occurs:

```python
def test_workflow_rejects_bluesky_did_alias_after_extraction_before_summary() -> None:
    events: list[str] = []
    repository = FakeRepository(records=[social_record_with_did_url()])
    workflow = make_workflow(
        events=events,
        repository=repository,
        article=make_article(source_type="social").model_copy(update={
            "canonical_url": "https://bsky.app/profile/did:plc:alice/post/3social"
        }),
    )

    with pytest.raises(DigestError) as raised:
        workflow.run("https://bsky.app/profile/alice.example/post/3social", NOW)

    assert raised.value.code == "DUPLICATE_URL"
    assert events == ["input", "extract"]
```

- [ ] **Step 2: Run the test and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow.py -k bluesky_did_alias -q
```

Expected: FAIL because the workflow currently proceeds to `summarize` after extraction.

- [ ] **Step 3: Add the minimal post-extraction duplicate guard**

Extract a focused helper and call it both before extraction and after resolving the article URL:

```python
def _has_canonical_url(repository: SummaryRepository, canonical_url: str) -> bool:
    return any(str(record.canonical_url) == canonical_url for record in repository.list())

# Existing local preflight remains before extraction.
# Immediately after extraction:
resolved_url = str(article.canonical_url)
if resolved_url != canonical_url and _has_canonical_url(self._repository, resolved_url):
    raise DigestError("input", "DUPLICATE_URL", "A summary already exists for this URL", False)
```

Do not suppress repository errors and do not call the summarizer before this check.

- [ ] **Step 4: Add a fixture-to-JSON local pipeline test**

Use a fake Bluesky extractor returning `sourceType="social"`, fake summarizer, fixed classifier, and temporary repository. Assert exactly one validated JSON record is written and can be retrieved by `list` and `get`, with DID canonical URL and `social` source type. Run the workflow a second time through a handle alias and assert `DUPLICATE_URL` with still exactly one JSON file.

- [ ] **Step 5: Run workflow, storage, and local integration tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow.py tests/test_storage.py tests/test_local_pipeline.py -q
```

Expected: all selected tests pass, with duplicate rejection occurring before paid-service fakes.

- [ ] **Step 6: Commit duplicate-safe integration**

```powershell
git add src/ai_digest/workflow.py tests/test_workflow.py tests/test_local_pipeline.py
git commit -m "fix: reject resolved Bluesky duplicates early"
```

### Task 6: Verify frontend rendering, complete regression gates, and record progress

**Files:**
- Modify: `site/src/lib/og-image.test.ts`
- Modify: `site/src/lib/summaries.test.ts`
- Modify: `progress.md`
- Modify: `todo.md`
- Modify if user-facing setup needs clarification: `README.md`

**Interfaces:**
- Consumes: validated `SummaryRecord` with `sourceType="social"`, existing Astro pages, OG renderer, CLI, GitHub Pages workflow, and approved design spec.
- Produces: verified local build support for social records, documented test evidence, and—only when separately authorized—one remote acceptance record.

- [ ] **Step 1: Add failing frontend social rendering tests**

Add a social record to summary loader/search coverage and verify the existing OG mapper produces the already-supported uppercase label:

```ts
expect(createOgImageContent({
  ...validRecord,
  sourceType: 'social',
  canonicalUrl: 'https://bsky.app/profile/did:plc:alice/post/3social',
})).toMatchObject({ sourceType: 'SOCIAL' });
```

Assert searching the social post title/text returns it and published filtering/date sorting remain unchanged.

- [ ] **Step 2: Run focused frontend tests and verify the intended state**

```powershell
Set-Location site
npm.cmd test -- --run src/lib/summaries.test.ts src/lib/og-image.test.ts
Set-Location ..
```

Expected before any necessary production adjustment: the new contract/rendering assertion exposes any missed `social` union or mapper branch. If it already passes because `toUpperCase()` supports `SOCIAL`, retain the regression test and make no unnecessary production change.

- [ ] **Step 3: Run the complete local verification matrix**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location site
npm.cmd test
npm.cmd run build
npm.cmd run build:pages
Set-Location ..
.\.venv\Scripts\python.exe scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
```

Expected: complete Python and Vitest suites pass; Astro check reports zero errors/warnings/hints; production and Pages builds succeed; tracked deployment verification and `git diff --check` exit 0.

- [ ] **Step 4: Scan tracked files and build output for credentials**

Run the repository's existing deployment verifier first. Then use tracked-file searches for forbidden credential assignments and inspect only matches, never printing `.env` contents:

```powershell
git grep -n -I -E "(OPENAI_API_KEY|GEMINI_API_KEY|GITHUB_TOKEN|Authorization: Bearer|app-password|Cookie:)" -- ':!*.example' ':!docs/**'
```

Expected: no committed secret values. Variable names in code may appear and must be reviewed as configuration references rather than treated as credentials.

- [ ] **Step 5: Update progress documents with verified local results**

In `progress.md`, add the Bluesky implementation date, completed components, exact test/build counts, risks, unverified remote items, and next action. In `todo.md`, check only implemented items that passed the preceding gates; leave live API, paid summarization, push, deployment, and remote Pages acceptance unchecked until actually completed.

- [ ] **Step 6: Commit verified implementation documentation**

```powershell
git add site/src/lib/og-image.test.ts site/src/lib/summaries.test.ts progress.md todo.md README.md
git diff --cached --check
git commit -m "docs: record Bluesky ingestion verification"
```

Omit `README.md` from `git add` if no user-facing instruction changed.

- [ ] **Step 7: Stop at the external-action approval gate**

Report local evidence and ask the user to provide or approve one stable public, non-reply Bluesky post URL and separately authorize the paid summary call, Git push, Pages workflow, and remote acceptance. Do not infer these permissions from approval of this implementation plan.

- [ ] **Step 8: When explicitly authorized, perform one live and remote acceptance**

Run `ai-digest add <approved-url>` once with the selected configured summarizer, inspect the saved JSON without exposing environment values, verify `sourceType="social"` and DID canonical URL, rerun local build/security gates, update `progress.md`/`todo.md`, commit only the acceptance record and generated summary, push, monitor the Pages workflow, and verify the public list/search/detail/source link/OG image. Record exact commit, workflow run, HTTP results, and any unverified item; never mark a failed or blocked check complete.

---

## Plan Self-Review Result

- Spec coverage: URL scope, isolated architecture, DID canonicalization, content mapping, reply rejection, errors, security, TDD, local integration, frontend rendering, and remote acceptance each map to an explicit task.
- Scope: one Bluesky source adapter and its required shared-contract changes; no unrelated platforms or optional features are included.
- Interface consistency: every task uses `social`, `BlueskyPostRef`, `BlueskyAppView`, `BlueskyAppViewClient`, `BlueskyExtractor`, and DID canonical URLs consistently.
- External actions: paid API, push, deployment, and live-source acceptance remain explicit execution-time approval gates.
