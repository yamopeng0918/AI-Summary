# GitHub Pages Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the verified Astro site at `https://yamopeng0918.github.io/AI-Summary/` from `master` through a gated GitHub Actions workflow.

**Architecture:** Add a tested base-path helper for all internal Astro links, portable Python verification utilities for deployment artifacts and public smoke checks, and an official `withastro/action` → `actions/deploy-pages` workflow. The workflow runs the complete Python and frontend suites, scans tracked and generated files, and deploys only after every build gate succeeds.

**Tech Stack:** Python 3.12+, pytest, Astro 7, TypeScript, Vitest, Node.js 24 in CI, npm lockfile installs, GitHub Actions, GitHub Pages.

## Global Constraints

- Deploy only the static site in `site/`; never place OpenAI credentials or other secrets in Actions or browser assets.
- Publish to `https://yamopeng0918.github.io/AI-Summary/` with `site: 'https://yamopeng0918.github.io'` and `base: '/AI-Summary'`.
- Trigger on pushes to `master` and `workflow_dispatch`.
- Gate deployment on complete Python tests, frontend tests, Astro check/build, tracked-file scanning, generated-output scanning, and base-path verification.
- Keep the approved `fictional-ai-digest-demo` record public in the initial deployment.
- Review locked `esbuild` and `sharp` install requirements before authorizing CI dependency scripts; do not add a global script approval.
- A failed deployment must preserve JSON, local data, the previous Pages release, artifacts, and retry logs.
- Do not mark Pages complete until the public homepage and demo detail page pass bounded smoke checks.
- Preserve the three existing untracked user files and never stage them.
- Remote Pages settings, pushes, and deployment require explicit user authorization at execution time.

---

## File Structure

- Create `site/src/lib/paths.ts`: one responsibility—construct internal URLs from Astro's base URL.
- Create `site/src/lib/paths.test.ts`: unit coverage for root and repository-subpath URLs.
- Modify `site/src/layouts/BaseLayout.astro`: use the helper for the site-name home link.
- Modify `site/src/pages/index.astro`: use the helper for summary detail links.
- Modify `site/src/pages/summaries/[id].astro`: use the helper for the back link while preserving external canonical URLs.
- Modify `site/astro.config.mjs`: configure the approved GitHub Pages origin and base path.
- Create `scripts/verify_deployment.py`: scan tracked/generated files and validate generated internal links.
- Create `tests/test_verify_deployment.py`: unit tests for detection, exclusions, and base-link checks.
- Create `scripts/smoke_pages.py`: bounded HTTP validation for the live Pages homepage and demo detail page.
- Create `tests/test_smoke_pages.py`: deterministic tests with mocked HTTP and sleep behavior.
- Create `.github/workflows/deploy-pages.yml`: build, deploy, permissions, concurrency, and live smoke orchestration.
- Modify `site/package.json`: add the Pages-specific build-and-verify command without changing normal local build behavior.
- Modify `README.md`: document Pages URL, workflow, manual retry, and local deployment checks.
- Modify `progress.md`: record only verified deployment facts and remaining risks.
- Modify `todo.md`: check only gates proven by local and public evidence.

### Task 1: Base-aware Astro internal links

**Files:**
- Create: `site/src/lib/paths.ts`
- Create: `site/src/lib/paths.test.ts`
- Modify: `site/src/layouts/BaseLayout.astro`
- Modify: `site/src/pages/index.astro`
- Modify: `site/src/pages/summaries/[id].astro`
- Modify: `site/astro.config.mjs`

**Interfaces:**
- Consumes: Astro `import.meta.env.BASE_URL` and validated summary IDs.
- Produces: `homePath(baseUrl: string): string` and `summaryPath(baseUrl: string, id: string): string`.

- [ ] **Step 1: Write failing base-path tests**

Create `site/src/lib/paths.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { homePath, summaryPath } from './paths';

describe('Pages paths', () => {
  it('normalizes the project base to one trailing slash', () => {
    expect(homePath('/AI-Summary')).toBe('/AI-Summary/');
    expect(homePath('/AI-Summary/')).toBe('/AI-Summary/');
  });

  it('keeps root deployments valid', () => {
    expect(homePath('/')).toBe('/');
  });

  it('builds a summary path below the configured base', () => {
    expect(summaryPath('/AI-Summary/', 'demo-id')).toBe('/AI-Summary/summaries/demo-id/');
  });
});
```

- [ ] **Step 2: Run the test and verify the red state**

Run from `site/`:

```powershell
npm.cmd test -- src/lib/paths.test.ts
```

Expected: FAIL because `./paths` does not exist.

- [ ] **Step 3: Implement the minimal path helper**

Create `site/src/lib/paths.ts`:

```ts
export function homePath(baseUrl: string): string {
  return baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
}

export function summaryPath(baseUrl: string, id: string): string {
  return `${homePath(baseUrl)}summaries/${encodeURIComponent(id)}/`;
}
```

- [ ] **Step 4: Replace hard-coded internal links**

In each Astro component, import the helper and bind the approved base:

```astro
---
import { homePath, summaryPath } from '../lib/paths';

const baseUrl = import.meta.env.BASE_URL;
---
```

Use `homePath(baseUrl)` for `/` links and `summaryPath(baseUrl, record.id)` for detail links. In `site/src/pages/summaries/[id].astro`, use the correct relative import `../../lib/paths`; leave `record.canonicalUrl` unchanged.

- [ ] **Step 5: Configure Astro for the project site**

Update `site/astro.config.mjs`:

```js
import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  srcDir: './src',
  site: 'https://yamopeng0918.github.io',
  base: '/AI-Summary',
});
```

- [ ] **Step 6: Run targeted and complete frontend verification**

Run from `site/`:

```powershell
npm.cmd test -- src/lib/paths.test.ts
npm.cmd test
npm.cmd run build
```

Expected: 3 path tests pass, the complete Vitest suite passes, Astro reports 0 errors/warnings/hints, and both static routes build.

- [ ] **Step 7: Commit the independently working link change**

```powershell
git add -- site/src/lib/paths.ts site/src/lib/paths.test.ts site/src/layouts/BaseLayout.astro site/src/pages/index.astro 'site/src/pages/summaries/[id].astro' site/astro.config.mjs
git commit -m "feat: support GitHub Pages base path"
```

### Task 2: Portable deployment artifact verifier

**Files:**
- Create: `scripts/verify_deployment.py`
- Create: `tests/test_verify_deployment.py`

**Interfaces:**
- Consumes: explicit file paths, a generated `site/dist` directory, and expected base `/AI-Summary/`.
- Produces: `scan_sensitive_files(paths: Iterable[Path]) -> list[str]`, `verify_generated_links(dist_root: Path, base_path: str) -> list[str]`, and a CLI exit code of 0 only when no violations exist.

- [ ] **Step 1: Write failing scanner tests**

Create tests covering these exact behaviors:

```python
from pathlib import Path

from scripts.verify_deployment import scan_sensitive_files, verify_generated_links


def test_sensitive_scan_flags_real_token_shapes(tmp_path: Path) -> None:
    leaked = tmp_path / "leaked.txt"
    leaked.write_text("OPENAI_API_KEY=sk-proj-" + "A" * 32, encoding="utf-8")
    assert scan_sensitive_files([leaked]) == [f"{leaked}: OpenAI API key"]


def test_sensitive_scan_allows_documented_placeholders(tmp_path: Path) -> None:
    example = tmp_path / "README.md"
    example.write_text("OPENAI_API_KEY=<your-openai-api-key>", encoding="utf-8")
    assert scan_sensitive_files([example]) == []


def test_generated_links_reject_root_relative_internal_urls(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text('<a href="/summaries/demo/">Demo</a>', encoding="utf-8")
    assert verify_generated_links(tmp_path, "/AI-Summary/") == [
        f"{index}: internal href /summaries/demo/ misses /AI-Summary/"
    ]


def test_generated_links_accept_pages_base_and_external_urls(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(
        '<a href="/AI-Summary/summaries/demo/">Demo</a>'
        '<a href="https://example.com/article">Source</a>',
        encoding="utf-8",
    )
    assert verify_generated_links(tmp_path, "/AI-Summary/") == []
```

Add equivalent cases for GitHub token forms, PEM private-key headers, a tracked file named `.env`, nested HTML files, and missing `dist`.

- [ ] **Step 2: Run tests and verify the red state**

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest tests/test_verify_deployment.py -v
```

Expected: collection FAIL because `scripts.verify_deployment` does not exist.

- [ ] **Step 3: Implement scanning and generated-link verification**

Implement `scripts/verify_deployment.py` with `pathlib`, `re`, `html.parser.HTMLParser`, `argparse`, and `subprocess.run(['git', 'ls-files'], check=True, capture_output=True, text=True)`. Use named patterns for:

```python
SENSITIVE_PATTERNS = {
    "OpenAI API key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
```

Treat a tracked path whose basename is exactly `.env` as a violation. Read UTF-8 text with decoding errors replaced; skip binary files containing a NUL byte. Parse every generated `*.html` `href`; allow `http:`, `https:`, `mailto:`, `tel:`, fragments, and paths beginning with the approved base. Report other root-relative internal links. The CLI accepts:

```text
--tracked
--dist PATH
--base /AI-Summary/
```

Print one violation per line to stderr and return 1 when violations exist.

- [ ] **Step 4: Run targeted tests and exercise the CLI**

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest tests/test_verify_deployment.py -v
python scripts/verify_deployment.py --tracked
Set-Location site
npm.cmd run build
Set-Location ..
python scripts/verify_deployment.py --dist site/dist --base /AI-Summary/
```

Expected: tests PASS and both CLI invocations exit 0 without violations.

- [ ] **Step 5: Commit the verifier**

```powershell
git add -- scripts/verify_deployment.py tests/test_verify_deployment.py
git commit -m "feat: verify deployment artifacts"
```

### Task 3: Bounded public Pages smoke checker

**Files:**
- Create: `scripts/smoke_pages.py`
- Create: `tests/test_smoke_pages.py`

**Interfaces:**
- Consumes: site root URL, demo ID, retry count, request timeout, and retry delay.
- Produces: `check_pages(...) -> list[str]` and a CLI that exits 0 only after both public checks succeed.

- [ ] **Step 1: Write failing deterministic smoke tests**

Use injected `fetch` and `sleep` callables so tests never use the network:

```python
from scripts.smoke_pages import check_pages


def test_pages_check_accepts_home_and_demo() -> None:
    responses = {
        "https://example.test/AI-Summary/": "<title>AI Digest</title>",
        "https://example.test/AI-Summary/summaries/demo/": "<h1>Demo</h1>",
    }
    assert check_pages(
        "https://example.test/AI-Summary/",
        "demo",
        attempts=1,
        delay_seconds=0,
        fetch=responses.__getitem__,
        sleep=lambda _: None,
    ) == []


def test_pages_check_retries_then_reports_failure() -> None:
    calls = []

    def failing_fetch(url: str) -> str:
        calls.append(url)
        raise OSError("not ready")

    errors = check_pages(
        "https://example.test/AI-Summary/",
        "demo",
        attempts=3,
        delay_seconds=0,
        fetch=failing_fetch,
        sleep=lambda _: None,
    )
    assert len(calls) == 6
    assert errors == [
        "homepage failed after 3 attempts: not ready",
        "demo page failed after 3 attempts: not ready",
    ]
```

Add a case where homepage HTTP succeeds but lacks `AI Digest`.

- [ ] **Step 2: Run tests and verify the red state**

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest tests/test_smoke_pages.py -v
```

Expected: collection FAIL because `scripts.smoke_pages` does not exist.

- [ ] **Step 3: Implement the minimal checker**

Use `urllib.request.urlopen` with an explicit timeout and a descriptive `User-Agent`. Normalize the site root to one trailing slash and derive:

```python
homepage_url = site_root
demo_url = f"{site_root}summaries/{quote(demo_id, safe='')}/"
```

Retry each URL exactly `attempts` times, sleep only between attempts, require `AI Digest` in homepage HTML, and treat any readable demo HTML as success. The CLI defaults are:

```text
--site-root https://yamopeng0918.github.io/AI-Summary/
--demo-id 20260809-fictional-ai-digest-demo
--attempts 6
--delay-seconds 10
--timeout-seconds 15
```

- [ ] **Step 4: Run tests**

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest tests/test_smoke_pages.py -v
```

Expected: all smoke checker tests PASS without network access.

- [ ] **Step 5: Commit the checker**

```powershell
git add -- scripts/smoke_pages.py tests/test_smoke_pages.py
git commit -m "feat: add Pages smoke checks"
```

### Task 4: Official Astro Pages workflow

**Files:**
- Create: `.github/workflows/deploy-pages.yml`
- Modify: `site/package.json`

**Interfaces:**
- Consumes: Task 2 verifier CLI, Task 3 smoke CLI, `site/package-lock.json`, and `master`.
- Produces: a Pages artifact, `github-pages` deployment, and public smoke result.

- [ ] **Step 1: Review locked native install requirements before workflow creation**

Run from `site/`:

```powershell
npm.cmd explain esbuild
npm.cmd explain sharp
npm.cmd audit --json
```

Expected: both native packages resolve only through the committed Astro dependency graph; audit reports 0 vulnerabilities. Record any different result and stop for review rather than globally approving scripts.

- [ ] **Step 2: Add a Pages-specific package script**

Add this script while preserving existing scripts:

```json
"build:pages": "astro check && astro build && python ../scripts/verify_deployment.py --dist dist --base /AI-Summary/"
```

Run from `site/`:

```powershell
npm.cmd run build:pages
```

Expected: Astro diagnostics are clean, two pages build, and artifact verification exits 0.

- [ ] **Step 3: Create the workflow using official actions**

Create `.github/workflows/deploy-pages.yml` with the official stable major versions verified during design (`actions/checkout@v7`, `actions/setup-python@v6`, `actions/setup-node@v6`, `withastro/action@v6`, and `actions/deploy-pages@v5`):

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [master]
  workflow_dispatch:

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: python -m pytest
      - run: python scripts/verify_deployment.py --tracked
      - uses: actions/setup-node@v6
        with:
          node-version: '24'
          cache: npm
          cache-dependency-path: site/package-lock.json
      - run: npm ci
        working-directory: site
      - run: npm test
        working-directory: site
      - uses: withastro/action@v6
        with:
          path: ./site
          node-version: '24'
          package-manager: npm
          build-cmd: npm run build:pages

  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v7
      - name: Deploy Pages artifact
        id: deployment
        uses: actions/deploy-pages@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - name: Verify public Pages site
        run: python scripts/smoke_pages.py
```

- [ ] **Step 4: Validate workflow content and local behavior**

```powershell
rg -n "branches: \[master\]|workflow_dispatch|contents: read|pages: write|id-token: write|cancel-in-progress: false|withastro/action|actions/deploy-pages|smoke_pages" .github/workflows/deploy-pages.yml
python scripts/verify_deployment.py --tracked
Set-Location site
npm.cmd test
npm.cmd run build:pages
Set-Location ..
git diff --check
```

Expected: every required workflow term is present, all commands exit 0, and no whitespace errors exist.

- [ ] **Step 5: Commit the workflow**

```powershell
git add -- .github/workflows/deploy-pages.yml site/package.json
git commit -m "ci: deploy Astro site to GitHub Pages"
```

### Task 5: Full local deployment gate and operating documentation

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: all locally verifiable outputs from Tasks 1–4.
- Produces: accurate operator instructions and a handoff that leaves remote deployment explicitly unverified.

- [ ] **Step 1: Run the complete local gate from a clean dependency state**

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest
Set-Location site
npm.cmd ci
npm.cmd test
npm.cmd run build:pages
npm.cmd audit --json
Set-Location ..
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
```

Expected: the Python count includes the new verifier/smoke tests with 0 failures; all frontend tests pass; Astro has 0 diagnostics and builds two pages; both scans exit 0; npm audit reports 0 vulnerabilities.

- [ ] **Step 2: Inspect generated URLs directly**

```powershell
rg -n 'href="/AI-Summary/|href="https://' site/dist
python scripts/verify_deployment.py --dist site/dist --base /AI-Summary/
```

Expected: the inspection shows internal links beginning with `/AI-Summary/`, and the authoritative verifier exits 0 with no invalid root-relative links.

- [ ] **Step 3: Document local and remote status precisely**

Update README with the expected public URL, automatic/manual triggers, `npm.cmd run build:pages`, public smoke command, and Actions retry location. Update progress/todo to mark workflow implementation and local gates complete but keep actual Pages deployment and public smoke acceptance unchecked until Task 6 succeeds.

- [ ] **Step 4: Verify document consistency**

```powershell
rg -n "AI-Summary|GitHub Pages|build:pages|UNVERIFIED|smoke" README.md progress.md todo.md
git diff --check
git status --short
```

Expected: all three documents distinguish local workflow readiness from real public deployment; only intended files plus the three pre-existing untracked user files appear.

- [ ] **Step 5: Commit the locally verified handoff**

```powershell
git add -- README.md progress.md todo.md
git commit -m "docs: document Pages deployment workflow"
```

### Task 6: Enable, deploy, and verify GitHub Pages

**Files:**
- Modify after successful public acceptance: `progress.md`
- Modify after successful public acceptance: `todo.md`

**Interfaces:**
- Consumes: user authorization, committed Tasks 1–5, GitHub repository admin access, and Actions logs.
- Produces: synchronized `master`, GitHub Actions Pages source, a successful deployment run, and public acceptance evidence.

- [ ] **Step 1: Re-run pre-push verification and inspect commit scope**

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m pytest
Set-Location site
npm.cmd test
npm.cmd run build:pages
Set-Location ..
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
git status --short --branch
git log --oneline origin/master..master
```

Expected: every gate exits 0; only the three existing user files are untracked; the log contains only reviewed deployment commits.

- [ ] **Step 2: Obtain explicit authorization for remote changes**

Ask the user to authorize all three external effects together: pushing `master`, setting Pages Source to GitHub Actions, and triggering/monitoring the first deployment. Do not infer this authorization from design approval.

- [ ] **Step 3: Push reviewed commits**

```powershell
git push origin master
```

Expected: GitHub accepts the reviewed `master` commits without force push.

- [ ] **Step 4: Configure Pages Source using the GitHub API or repository UI**

First inspect:

```powershell
gh api repos/yamopeng0918/AI-Summary/pages
```

If Pages does not exist (HTTP 404), create it:

```powershell
gh api --method POST repos/yamopeng0918/AI-Summary/pages -f build_type=workflow
```

If Pages exists with another build type, update it:

```powershell
gh api --method PUT repos/yamopeng0918/AI-Summary/pages -f build_type=workflow
```

Expected: the resulting Pages object reports `build_type: workflow`. If `gh` authentication or repository permissions are unavailable, stop and give the user the exact UI path: repository **Settings → Pages → Build and deployment → Source → GitHub Actions**.

- [ ] **Step 5: Monitor the first workflow run**

```powershell
$runId = gh run list --workflow deploy-pages.yml --branch master --limit 1 --json databaseId --jq '.[0].databaseId'
if (-not $runId) { throw 'No deploy-pages workflow run found for master' }
gh run watch $runId --exit-status
```

Expected: build, deploy, and public smoke steps all succeed. On failure, inspect with `gh run view $runId --log-failed`; do not delete data or mark deployment complete.

- [ ] **Step 6: Independently verify the public URLs**

```powershell
python scripts/smoke_pages.py --site-root https://yamopeng0918.github.io/AI-Summary/ --demo-id 20260809-fictional-ai-digest-demo --attempts 6 --delay-seconds 10 --timeout-seconds 15
```

Expected: exit 0 after both homepage and demo detail page checks succeed.

- [ ] **Step 7: Record real deployment evidence**

Only after Steps 5–6 succeed, update progress/todo with the deployment date, workflow run URL/ID, public URL, tested commit hash, and completed Pages checkboxes. If either check fails, record the blocker as unverified instead.

- [ ] **Step 8: Verify, commit, and request push authorization for the evidence update**

```powershell
rg -n "GitHub Pages|yamopeng0918.github.io/AI-Summary|workflow|smoke" progress.md todo.md
git diff --check
git add -- progress.md todo.md
git commit -m "docs: record GitHub Pages deployment"
git status --short --branch
```

Expected: one documentation-only commit and the same three pre-existing untracked files. Obtain explicit authorization before pushing this final evidence commit.
