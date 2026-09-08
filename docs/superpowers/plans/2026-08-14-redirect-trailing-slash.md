# Redirect Trailing-Slash Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent canonical trailing-slash normalization from creating redirect loops while preserving all existing URL identity and SSRF protections.

**Architecture:** Extend the extractor's validated connection target to carry a canonical URL separately from the transport URL. Canonicalization remains unchanged for saved identity; each safe redirect transport URL retains the server-provided trailing slash and is resolved independently before the next pinned request.

**Tech Stack:** Python 3.12+, HTTPX, pytest, Pydantic, Trafilatura

## Global Constraints

- Keep the stored canonical URL format, JSON Schema, CLI interface, redirect limit, pinned-IP connection, Host header, SNI, and structured errors unchanged.
- Validate every input and redirect destination as a public HTTP(S) URL before connecting.
- Use TDD: observe the focused regression test fail before editing production code.
- Do not require external network or Gemini in automated tests.
- Preserve unrelated user files and changes.

---

### Task 1: Separate canonical and transport redirect URLs

**Files:**
- Modify: `tests/test_web_extractor.py`
- Modify: `src/ai_digest/extractors/web.py`

**Interfaces:**
- Consumes: `normalize_public_url(raw_url: str) -> str`, `_validate_destination(url: str) -> _ConnectionTarget`, and `WebExtractor.extract(url: str) -> ExtractedArticle`.
- Produces: `_ConnectionTarget.canonical_url: str` for identity and `_ConnectionTarget.url: str` for slash-preserving HTTP transport.

- [ ] **Step 1: Write the failing regression test**

Add next to the existing redirect tests:

```python
def test_preserves_redirect_trailing_slash_for_transport() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/article":
            return httpx.Response(301, headers={"location": "/article/"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=FIXTURE)

    article = WebExtractor(client_for(httpx.MockTransport(handler))).extract(
        "https://example.com/article/"
    )

    assert requested_paths == ["/article", "/article/"]
    assert str(article.canonical_url) == "https://example.com/article"
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_extractor.py::test_preserves_redirect_trailing_slash_for_transport -v
```

Expected: FAIL with `TOO_MANY_REDIRECTS`, proving that redirect validation removes the slash before transport.

- [ ] **Step 3: Implement the minimal separation**

Change `_ConnectionTarget` to carry both URL roles:

```python
@dataclass(frozen=True)
class _ConnectionTarget:
    url: str
    canonical_url: str
    address: str
    host: str
    host_header: str
```

In `_validate_destination`, validate and canonicalize with `normalize_public_url`, but reconstruct `transport_url` from the parsed original path after validation so a non-root trailing slash is retained. Return both values:

```python
return _ConnectionTarget(
    transport_url,
    normalized,
    validated_addresses[0],
    host,
    host_header,
)
```

Resolve relative redirects against `target.url` as today. On successful extraction, pass `target.canonical_url` to `_extract_article` instead of `target.url`.

- [ ] **Step 4: Run focused extractor verification and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web_extractor.py -v
```

Expected: all extractor tests PASS, including the new regression, redirect-limit, private-target, pinned-IP, Host, and SNI coverage.

- [ ] **Step 5: Run the complete Python suite and diff validation**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
git diff --check
```

Expected: all tests PASS and `git diff --check` exits 0.

- [ ] **Step 6: Commit the isolated code fix**

```powershell
git add tests/test_web_extractor.py src/ai_digest/extractors/web.py
git commit -m "fix: preserve redirect trailing slash for transport"
```

### Task 2: Complete live Gemini acceptance and project records

**Files:**
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: `.venv\Scripts\ai-digest.exe add <url>`, `GEMINI_API_KEY`, and `AI_DIGEST_SUMMARY_ROOT`.
- Produces: one Schema-valid temporary summary JSON and verified progress documentation.

- [ ] **Step 1: Run one isolated live acceptance**

Set `AI_DIGEST_PROVIDER=gemini` and a unique temporary `AI_DIGEST_SUMMARY_ROOT`, then run:

```powershell
.\.venv\Scripts\ai-digest.exe add 'https://pala.tw/python-web-crawler/'
```

Expected: progress stages `input`, `extract`, `summarize`, `classify`, `save`, then `complete`, with exit code 0 and exactly one JSON file in the temporary directory.

- [ ] **Step 2: Validate and inspect the generated record**

Load the generated JSON through `SummaryRepository`, confirm its canonical URL is `https://pala.tw/python-web-crawler`, status is `published`, key-point count is 3–5, category is valid, tags are non-empty, and no credential names or key values appear in the file.

- [ ] **Step 3: Update progress records**

Record the date, approved source URL, provider/model, command outcome, generated record ID, and validation evidence in `progress.md`. Mark only the live Gemini acceptance checkbox complete in `todo.md`; do not mark the classifier, YouTube, or social-source milestones complete.

- [ ] **Step 4: Verify documentation and repository state**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
git diff --check
git status --short
```

Expected: full suite PASS; diff check exits 0; only intended documentation changes and pre-existing user files remain.

- [ ] **Step 5: Commit the verified acceptance documentation**

```powershell
git add progress.md todo.md
git commit -m "docs: record Gemini live acceptance"
```
