# Gemini Provider Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini as the default, explicitly selectable summary provider while preserving the existing OpenAI provider and CLI behavior.

**Architecture:** Keep provider selection in the CLI composition root and implement Gemini as a separate adapter satisfying the existing `Summarizer` protocol. The adapter uses the official `google-genai` SDK structured-output interface and maps provider-specific failures into the existing provider-neutral `DigestError` contract.

**Tech Stack:** Python 3.12+, Pydantic 2, Typer, Google Gen AI SDK (`google-genai>=2.7,<3`), OpenAI SDK, pytest, Astro/Vitest.

## Global Constraints

- `AI_DIGEST_PROVIDER` accepts only `gemini` or `openai`; missing means `gemini` and an unknown value returns `input / INVALID_PROVIDER`.
- Gemini uses `GEMINI_API_KEY` and defaults `GEMINI_MODEL` to `gemini-2.5-flash`.
- OpenAI continues to use `OPENAI_API_KEY` and defaults `OPENAI_MODEL` to `gpt-5-mini`.
- Do not automatically fall back between providers.
- Do not change `SummaryDraft`, persisted summary schema, extraction, classification, or Astro presentation.
- Errors must not expose API keys, article text, or canonical URLs.
- Preserve the three unrelated untracked user files in the repository root; never stage them.

---

## File Structure

- Create `src/ai_digest/summarizers/gemini.py`: Gemini SDK adapter and provider-specific error mapping.
- Create `tests/test_gemini_summarizer.py`: adapter request, response, refusal, and error-contract tests.
- Modify `src/ai_digest/cli.py`: provider selection and SDK client construction only.
- Modify `tests/test_cli.py`: composition-root and configuration behavior tests.
- Modify `pyproject.toml`: add the bounded runtime SDK dependency.
- Modify `.env.example` and `README.md`: document provider selection and both provider configurations.
- Modify `progress.md` and `todo.md`: record implementation and distinguish automated verification from live Gemini acceptance.

### Task 1: Gemini structured-output adapter

**Files:**
- Create: `tests/test_gemini_summarizer.py`
- Create: `src/ai_digest/summarizers/gemini.py`

**Interfaces:**
- Consumes: `ExtractedArticle`, `SummaryDraft`, and `DigestError` from `ai_digest.domain`; a client exposing `models.generate_content(model=..., contents=..., config=...)`.
- Produces: `class GeminiSummarizer(client: Any, model: str)` with `summarize(article: ExtractedArticle) -> SummaryDraft`.

- [ ] **Step 1: Write the failing success-path test**

Create a fake client that records `generate_content` arguments and returns `SimpleNamespace(parsed=make_draft(), candidates=[object()], prompt_feedback=None)`. Assert that `GeminiSummarizer(...).summarize(article)` returns the draft and that the call uses the selected model plus a `GenerateContentConfig` whose `response_mime_type` is `application/json` and `response_schema` is `SummaryDraft`.

```python
def test_gemini_summarizer_uses_structured_output_and_returns_validated_draft() -> None:
    client = FakeClient(SimpleNamespace(parsed=make_draft(), candidates=[object()], prompt_feedback=None))
    summarizer: Summarizer = GeminiSummarizer(client, "test-gemini")

    result = summarizer.summarize(make_article())

    assert result == make_draft()
    call = client.models.calls[0]
    assert call["model"] == "test-gemini"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is SummaryDraft
    assert make_article().title in call["contents"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `$env:PYTHONPATH="$PWD\src"; python -m pytest tests/test_gemini_summarizer.py::test_gemini_summarizer_uses_structured_output_and_returns_validated_draft -q`

Expected: FAIL because `ai_digest.summarizers.gemini` does not exist.

- [ ] **Step 3: Implement the minimal successful adapter**

Use `types.GenerateContentConfig(response_mime_type="application/json", response_schema=SummaryDraft, system_instruction=_SYSTEM_INSTRUCTION)`, call `client.models.generate_content`, and validate `response.parsed` with `SummaryDraft.model_validate`. Keep the prompt limited to the article title and text and reuse the behavioral requirements of the existing OpenAI system instruction.

```python
class GeminiSummarizer:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def summarize(self, article: ExtractedArticle) -> SummaryDraft:
        response = self._client.models.generate_content(
            model=self._model,
            contents=f"標題：{article.title}\n\n內容：{article.text}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=SummaryDraft,
            ),
        )
        return SummaryDraft.model_validate(response.parsed)
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command.

Expected: `1 passed`.

- [ ] **Step 5: Commit the successful adapter slice**

```powershell
git add -- tests/test_gemini_summarizer.py src/ai_digest/summarizers/gemini.py
git commit -m "feat: add Gemini structured summarizer"
```

### Task 2: Gemini error and refusal mapping

**Files:**
- Modify: `tests/test_gemini_summarizer.py`
- Modify: `src/ai_digest/summarizers/gemini.py`

**Interfaces:**
- Consumes: Google SDK `errors.ClientError`, `errors.ServerError`, and transport-level `httpx.TimeoutException` / `httpx.TransportError`.
- Produces: stable `DigestError(stage, code, message, retryable)` values identical in shape to the OpenAI adapter.

- [ ] **Step 1: Add failing parameterized error tests**

Add cases for `httpx.ReadTimeout` → `TIMEOUT/True`, `httpx.ConnectError` → `REQUEST_FAILED/True`, `ClientError(429, ...)` → `RATE_LIMITED/True`, other `ClientError` → `REQUEST_FAILED/False`, and `ServerError(500, ...)` → `REQUEST_FAILED/True`. Assert the public error message contains neither `article.text` nor its canonical URL.

```python
@pytest.mark.parametrize(
    ("outcome", "code", "retryable"),
    [
        (httpx.ReadTimeout("slow"), "TIMEOUT", True),
        (httpx.ConnectError("offline"), "REQUEST_FAILED", True),
        (ClientError(429, {"error": {"code": 429, "message": "quota"}}), "RATE_LIMITED", True),
        (ClientError(400, {"error": {"code": 400, "message": "bad"}}), "REQUEST_FAILED", False),
        (ServerError(500, {"error": {"code": 500, "message": "down"}}), "REQUEST_FAILED", True),
    ],
)
def test_gemini_summarizer_maps_provider_failures(outcome, code, retryable) -> None:
    article = make_article()
    with pytest.raises(DigestError) as raised:
        GeminiSummarizer(FakeClient(outcome), "test-gemini").summarize(article)
    assert (raised.value.stage, raised.value.code, raised.value.retryable) == (
        "summarize", code, retryable
    )
    assert article.text not in raised.value.message
    assert str(article.canonical_url) not in raised.value.message
```

- [ ] **Step 2: Add failing invalid-response and refusal tests**

Cover `parsed=None`, a malformed parsed mapping, and a response with no candidates plus `prompt_feedback.block_reason`; expect `INVALID_RESPONSE`, `INVALID_RESPONSE`, and `REFUSAL`, all non-retryable.

- [ ] **Step 3: Run adapter tests and verify RED**

Run: `$env:PYTHONPATH="$PWD\src"; python -m pytest tests/test_gemini_summarizer.py -q`

Expected: the new error/refusal cases fail by leaking SDK exceptions or validation exceptions.

- [ ] **Step 4: Implement minimal safe mappings**

Catch timeout before the broader transport error, map `errors.ClientError.code == 429` separately, map `errors.ServerError` as retryable, and convert `ValidationError`, `AttributeError`, `TypeError`, and missing parsed data to `INVALID_RESPONSE`. Check prompt blocking before parsed validation.

```python
except httpx.TimeoutException as error:
    raise DigestError("summarize", "TIMEOUT", "Summary request timed out", True) from error
except httpx.TransportError as error:
    raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", True) from error
except errors.ClientError as error:
    if error.code == 429:
        raise DigestError("summarize", "RATE_LIMITED", "Summary service is rate limited", True) from error
    raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", False) from error
except errors.ServerError as error:
    raise DigestError("summarize", "REQUEST_FAILED", "Summary request failed", True) from error
```

- [ ] **Step 5: Run adapter tests and verify GREEN**

Run the Step 3 command.

Expected: all Gemini adapter tests pass.

- [ ] **Step 6: Commit the error-contract slice**

```powershell
git add -- tests/test_gemini_summarizer.py src/ai_digest/summarizers/gemini.py
git commit -m "test: cover Gemini provider failures"
```

### Task 3: Provider-aware CLI composition

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_digest/cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `AI_DIGEST_PROVIDER`, provider-specific key/model environment variables, `genai.Client`, `GeminiSummarizer`, and existing OpenAI composition.
- Produces: `_workflow()` that defaults to Gemini, selects OpenAI explicitly, and raises provider-neutral configuration errors.

- [ ] **Step 1: Add failing CLI configuration tests**

Split the existing production wiring test into explicit cases:

```python
def test_production_defaults_to_gemini(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AI_DIGEST_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    # Replace genai.Client, GeminiSummarizer, and AddArticleWorkflow with recording fakes.
    cli._workflow()
    assert captured["gemini_api_key"] == "test-key"
    assert captured["summarizer_model"] == "gemini-2.5-flash"

def test_production_can_select_openai(monkeypatch) -> None:
    monkeypatch.setenv("AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cli._workflow()
    assert captured["summarizer_model"] == "gpt-5-mini"
```

Add focused tests asserting unknown provider produces `INVALID_PROVIDER`, missing Gemini key mentions only `GEMINI_API_KEY`, missing OpenAI key mentions only `OPENAI_API_KEY`, and local commands still work without any provider key.

- [ ] **Step 2: Run focused CLI tests and verify RED**

Run: `$env:PYTHONPATH="$PWD\src"; python -m pytest tests/test_cli.py -q`

Expected: Gemini-default and provider-selection assertions fail because `_workflow` is OpenAI-only.

- [ ] **Step 3: Add the SDK dependency**

Add `"google-genai>=2.7,<3"` to `[project].dependencies` in `pyproject.toml`, then install the editable development environment with:

Run: `python -m pip install -e ".[dev]"`

Expected: installation succeeds and `python -c "from google import genai"` exits 0.

- [ ] **Step 4: Implement provider selection in `_workflow`**

Add a small `_summarizer()` helper so key validation and client creation remain separate from extractor/repository wiring.

```python
def _summarizer() -> Summarizer:
    provider = os.environ.get("AI_DIGEST_PROVIDER", "gemini").strip().lower()
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise DigestError("input", "MISSING_API_KEY", "GEMINI_API_KEY is required for add", False)
        return GeminiSummarizer(
            genai.Client(api_key=api_key),
            os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        )
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise DigestError("input", "MISSING_API_KEY", "OPENAI_API_KEY is required for add", False)
        return OpenAISummarizer(OpenAI(api_key=api_key), os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    raise DigestError("input", "INVALID_PROVIDER", "AI_DIGEST_PROVIDER must be gemini or openai", False)
```

Use `_summarizer()` in `_workflow`; do not alter `create_app` or local command dependency injection.

- [ ] **Step 5: Run CLI and full Python tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH="$PWD\src"
python -m pytest tests/test_cli.py -q
python -m pytest -q
```

Expected: focused CLI tests pass; the full Python suite reports zero failures.

- [ ] **Step 6: Commit provider composition**

```powershell
git add -- tests/test_cli.py src/ai_digest/cli.py pyproject.toml
git commit -m "feat: select Gemini or OpenAI provider"
```

### Task 4: Configuration documentation and project tracking

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: exact environment behavior delivered by Task 3.
- Produces: copy-pasteable PowerShell setup for both providers and an accurate verification record.

- [ ] **Step 1: Update `.env.example` without secrets**

Use exactly:

```dotenv
AI_DIGEST_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
```

- [ ] **Step 2: Update README provider instructions**

State that Gemini is the default and show explicit PowerShell examples for Gemini and OpenAI. Explain there is no automatic fallback and that only the selected provider key is required for `add`; local `list`, `show`, `archive`, and `publish` do not require either key.

- [ ] **Step 3: Update progress and todo truthfully**

Mark provider selection and automated tests complete only after Task 3 passes. Keep live Gemini acceptance as `UNVERIFIED` unless Task 5 succeeds with a real key and public article; do not mark it complete based on fake-client tests.

- [ ] **Step 4: Validate documentation and secret hygiene**

Run:

```powershell
git diff --check
rg -n "AI_DIGEST_PROVIDER|GEMINI_API_KEY|GEMINI_MODEL|OPENAI_API_KEY|OPENAI_MODEL" .env.example README.md progress.md todo.md
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
```

Expected: no whitespace errors; all variables are documented; tracked/deployment verification finds no secrets.

- [ ] **Step 5: Commit documentation**

```powershell
git add -- .env.example README.md progress.md todo.md
git commit -m "docs: document Gemini provider setup"
```

### Task 5: Full verification and live Gemini acceptance

**Files:**
- Potentially create: one generated JSON beneath `data/summaries/` only if the user authorizes retaining the live acceptance output.
- Modify: `progress.md` and `todo.md` only if live acceptance succeeds.

**Interfaces:**
- Consumes: completed provider implementation, a process-scoped `GEMINI_API_KEY`, and a readable public article URL.
- Produces: complete automated verification evidence and, when credentials exist, a real persisted summary plus rebuilt site.

- [ ] **Step 1: Run all automated gates**

Run:

```powershell
$env:PYTHONPATH="$PWD\src"
python -m pytest -q
Set-Location site
npm.cmd test
npm.cmd run build:pages
Set-Location ..
git diff --check
```

Expected: all Python and Vitest tests pass, Astro reports zero diagnostics, Pages build/secret scan exits 0, and `git diff --check` exits 0.

- [ ] **Step 2: Check live credential availability without printing it**

Run:

```powershell
[pscustomobject]@{
  GeminiKeyConfigured = -not [string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY)
  Provider = $(if ($env:AI_DIGEST_PROVIDER) { $env:AI_DIGEST_PROVIDER } else { 'gemini (default)' })
}
```

Expected: only configuration status is printed, never the key value.

- [ ] **Step 3: Run live acceptance when the key is configured**

Set `AI_DIGEST_PROVIDER=gemini`, use Google DeepMind's public Gemini introduction article, and isolate output in a temporary summary directory first:

```powershell
$env:AI_DIGEST_PROVIDER='gemini'
$acceptanceRoot=Join-Path ([System.IO.Path]::GetTempPath()) 'ai-digest-gemini-acceptance'
$env:AI_DIGEST_SUMMARY_ROOT=$acceptanceRoot
ai-digest add 'https://deepmind.google/discover/blog/welcome-to-the-gemini-era/'
ai-digest list
```

Expected: stage events reach `complete`; exactly one validated JSON file exists beneath `$acceptanceRoot`; no key appears in output or JSON. If retention is desired, ask before copying the generated record into `data/summaries` because that changes published content.

- [ ] **Step 4: Rebuild against retained data or preserve UNVERIFIED status**

If the user authorizes retaining the record, copy only the validated JSON to `data/summaries`, run `npm.cmd run build:pages`, and verify its route exists in `site/dist`. If no key is configured or the API cannot be called, leave live acceptance marked `UNVERIFIED` and report the exact blocker without changing the automated-test result.

- [ ] **Step 5: Record successful live evidence, if any**

Only after live success, update `progress.md` and `todo.md` with the date, provider/model, public source URL, generated record ID, and build result; never record the API key. Commit the record and tracking changes only with explicit user approval:

```powershell
$recordPath=(Get-ChildItem -LiteralPath data/summaries -File -Filter '*.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
git add -- $recordPath progress.md todo.md
git commit -m "test: record Gemini end-to-end acceptance"
```

- [ ] **Step 6: Verify final Git scope**

Run: `git status --short; git log -6 --oneline`

Expected: only intentional task changes are committed or listed; the three pre-existing user files remain untracked and untouched.
