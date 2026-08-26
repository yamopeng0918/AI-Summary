# Summary OG Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one deterministic 1200 × 630 PNG for every published summary, expose it through Astro, use it in detail-page social metadata, and display it on homepage cards.

**Architecture:** The existing validated published-summary loader remains the only data source. A focused TypeScript renderer converts display-safe summary fields to Satori SVG and then Sharp PNG; an Astro static endpoint exposes those bytes under the existing Pages base path. Shared path helpers feed both page metadata and card markup, while the deployment verifier confirms that generated HTML references real, valid PNG assets.

**Tech Stack:** Astro 7.2, TypeScript 5.8, Vitest 3.2, Satori, Sharp 0.35.3, Python 3 deployment verifier, Noto Serif TC under OFL-1.1.

## Global Constraints

- Generate only from records returned by `loadPublishedSummaries()`; invalid and archived records remain fail-closed.
- Output must be a non-empty PNG with exact dimensions 1200 × 630.
- Use the approved editorial layout: warm white `#f7f2e7`, dark green `#17352d`, orange `#ef6a47`.
- Show `AI DIGEST`, category, title, one-to-two summary lines, source label, and uppercase source type.
- Source label is the non-blank author when available; otherwise it is `new URL(canonicalUrl).hostname`.
- Bundle Noto Serif TC variable TTF and OFL-1.1 license in the repository; no runtime or build-time font download is allowed.
- Do not change the summary JSON Schema or write generated PNG files into `data/summaries`.
- Generated PNG files live only in `site/dist/og/`; do not track build output.
- Homepage cards display the image; detail-page body does not.
- Metadata URLs must be absolute HTTPS URLs and must preserve the `/AI-Summary/` production base.
- Every behavior change follows strict RED, GREEN, refactor TDD.
- Do not stage or modify the user's unrelated untracked files or the pre-existing uncommitted `progress.md` change except in the final documentation task.

---

### Task 1: Add deterministic OG display-model helpers and font assets

**Files:**
- Modify: `site/package.json`
- Modify: `site/package-lock.json`
- Create: `site/src/assets/fonts/NotoSerifTC-VariableFont_wght.ttf`
- Create: `site/src/assets/fonts/OFL.txt`
- Create: `site/src/lib/og-image.ts`
- Create: `site/src/lib/og-image.test.ts`

**Interfaces:**
- Consumes: `SummaryRecord` from `site/src/lib/summaries.ts`.
- Produces: `OgImageContent`, `createOgImageContent(record: SummaryRecord): OgImageContent`, and `fitOgText(text: string, limits: readonly number[]): string[]`.

- [ ] **Step 1: Write failing tests for source selection, source type, line fitting, and hostile text**

Create `site/src/lib/og-image.test.ts` with a valid `SummaryRecord` fixture and these assertions:

```ts
import { describe, expect, it } from 'vitest';
import type { SummaryRecord } from './summaries';
import { createOgImageContent, fitOgText } from './og-image';

const record: SummaryRecord = {
  schemaVersion: 1,
  id: 'demo',
  canonicalUrl: 'https://news.example.com/articles/demo',
  sourceType: 'web',
  title: '這是一篇需要自動換行的繁體中文長標題',
  author: '王小明',
  sourcePublishedAt: null,
  createdAt: '2026-08-26T17:00:00+08:00',
  updatedAt: '2026-08-26T17:00:00+08:00',
  summary: '第一句摘要說明文章內容。第二句補充關鍵背景。第三句不應完整顯示。',
  keyPoints: ['重點一', '重點二', '重點三'],
  category: '人工智慧',
  tags: ['AI'],
  editorial: '編輯觀點',
  status: 'published',
};

describe('OG image content', () => {
  it('uses author before hostname and uppercases source type', () => {
    expect(createOgImageContent(record)).toMatchObject({ source: '王小明', sourceType: 'WEB' });
  });

  it('falls back to canonical hostname when author is absent', () => {
    expect(createOgImageContent({ ...record, author: null }).source).toBe('news.example.com');
  });

  it('fits text deterministically and adds one ellipsis only when truncated', () => {
    expect(fitOgText('ABCDEFGHIJK', [4, 4])).toEqual(['ABCD', 'EFG…']);
    expect(fitOgText('ABCDEFGH', [4, 4])).toEqual(['ABCD', 'EFGH']);
  });

  it('keeps hostile text as inert content', () => {
    expect(createOgImageContent({ ...record, title: '<script>alert(1)</script>' }).title)
      .toBe('<script>alert(1)</script>');
  });
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run from `site/`:

```powershell
npm.cmd test -- src/lib/og-image.test.ts
```

Expected: FAIL because `./og-image` does not exist.

- [ ] **Step 3: Install direct rendering dependencies and add licensed font assets**

Run from `site/` after network approval:

```powershell
npm.cmd install --save-exact satori sharp@0.35.3
Invoke-WebRequest 'https://raw.githubusercontent.com/google/fonts/main/ofl/notoseriftc/NotoSerifTC%5Bwght%5D.ttf' -OutFile 'src/assets/fonts/NotoSerifTC-VariableFont_wght.ttf'
Invoke-WebRequest 'https://raw.githubusercontent.com/google/fonts/main/ofl/notoseriftc/OFL.txt' -OutFile 'src/assets/fonts/OFL.txt'
```

Confirm both downloaded files are non-empty and `OFL.txt` contains `SIL OPEN FONT LICENSE Version 1.1`. Do not execute either download during normal tests or builds.

- [ ] **Step 4: Implement the minimal pure display model**

Create `site/src/lib/og-image.ts` with these public types and functions:

```ts
import type { SummaryRecord } from './summaries';

export interface OgImageContent {
  title: string;
  summary: string;
  category: string;
  source: string;
  sourceType: 'WEB' | 'YOUTUBE' | 'SOCIAL';
}

export function fitOgText(text: string, limits: readonly number[]): string[] {
  const characters = Array.from(text.trim());
  const lines: string[] = [];
  let offset = 0;
  for (const limit of limits) {
    if (offset >= characters.length) break;
    const remaining = characters.length - offset;
    const take = Math.min(limit, remaining);
    lines.push(characters.slice(offset, offset + take).join(''));
    offset += take;
  }
  if (offset < characters.length && lines.length > 0) {
    const last = lines.length - 1;
    lines[last] = `${Array.from(lines[last]).slice(0, -1).join('')}…`;
  }
  return lines;
}

export function createOgImageContent(record: SummaryRecord): OgImageContent {
  return {
    title: record.title,
    summary: record.summary,
    category: record.category,
    source: record.author?.trim() || new URL(record.canonicalUrl).hostname,
    sourceType: record.sourceType.toUpperCase() as OgImageContent['sourceType'],
  };
}
```

- [ ] **Step 5: Run the focused test and confirm GREEN**

Run: `npm.cmd test -- src/lib/og-image.test.ts`

Expected: all tests in `og-image.test.ts` PASS.

- [ ] **Step 6: Commit the self-contained helper and dependency unit**

```powershell
git add -- site/package.json site/package-lock.json site/src/assets/fonts site/src/lib/og-image.ts site/src/lib/og-image.test.ts
git commit -m "feat: add OG image content model"
```

### Task 2: Render and serve 1200 × 630 PNGs

**Files:**
- Modify: `site/src/lib/og-image.ts`
- Modify: `site/src/lib/og-image.test.ts`
- Create: `site/src/pages/og/[id].png.ts`
- Create: `site/src/pages/og/og-route.test.ts`

**Interfaces:**
- Consumes: `createOgImageContent(record)` from Task 1 and `loadPublishedSummaries()` from `summary-loader.ts`.
- Produces: `renderOgImage(record: SummaryRecord): Promise<Buffer>` and a prerendered PNG endpoint.

- [ ] **Step 1: Add a failing renderer test**

Extend `og-image.test.ts`:

```ts
import sharp from 'sharp';
import { renderOgImage } from './og-image';

it('renders a non-empty 1200 by 630 PNG with Chinese content', async () => {
  const png = await renderOgImage(record);
  const metadata = await sharp(png).metadata();
  expect(png.byteLength).toBeGreaterThan(1_000);
  expect(metadata).toMatchObject({ format: 'png', width: 1200, height: 630 });
});
```

- [ ] **Step 2: Run the renderer test and confirm RED**

Run: `npm.cmd test -- src/lib/og-image.test.ts`

Expected: FAIL because `renderOgImage` is not exported.

- [ ] **Step 3: Implement the approved editorial renderer**

In `og-image.ts`, load the font once with `readFile` and `new URL('../assets/fonts/NotoSerifTC-VariableFont_wght.ttf', import.meta.url)`. Implement `renderOgImage` by passing a Satori element tree with fixed `width: 1200`, `height: 630`, approved colors, title lines from `fitOgText(content.title, [22, 22, 22])`, and summary lines from `fitOgText(content.summary, [46, 46])`; convert the SVG with:

```ts
const png = await sharp(Buffer.from(svg)).png().toBuffer();
const metadata = await sharp(png).metadata();
if (metadata.format !== 'png' || metadata.width !== 1200 || metadata.height !== 630) {
  throw new Error('OG image renderer produced invalid PNG dimensions');
}
return png;
```

Register the bundled font in Satori as `Noto Serif TC`, data `fontData`, weight `400`, style `normal`; use the same font at higher CSS weights so the single variable file supplies the approved hierarchy. Keep all record strings as React/Satori text children, never as raw HTML.

- [ ] **Step 4: Run the renderer test and confirm GREEN**

Run: `npm.cmd test -- src/lib/og-image.test.ts`

Expected: all OG content and PNG tests PASS.

- [ ] **Step 5: Write a failing static-route test**

Create `site/src/pages/og/og-route.test.ts` that imports the endpoint module and asserts:

```ts
import { describe, expect, it } from 'vitest';
import sharp from 'sharp';
import { GET, getStaticPaths } from './[id].png';

describe('OG PNG route', () => {
  it('creates paths only from the published-summary loader result', async () => {
    const paths = await getStaticPaths();
    expect(paths.length).toBeGreaterThan(0);
    expect(paths.every((path) => typeof path.params.id === 'string')).toBe(true);
  });

  it('returns a valid PNG response for route props', async () => {
    const [{ props }] = await getStaticPaths();
    const response = await GET({ props } as Parameters<typeof GET>[0]);
    const bytes = Buffer.from(await response.arrayBuffer());
    expect(response.headers.get('content-type')).toBe('image/png');
    expect(await sharp(bytes).metadata()).toMatchObject({ format: 'png', width: 1200, height: 630 });
  });
});
```

- [ ] **Step 6: Run the route test and confirm RED**

Run: `npm.cmd test -- src/pages/og/og-route.test.ts`

Expected: FAIL because `[id].png.ts` does not exist.

- [ ] **Step 7: Implement the prerendered endpoint**

Create `[id].png.ts` with `export const prerender = true`, a `getStaticPaths()` that maps `loadPublishedSummaries()` to `{ params: { id }, props: { record } }`, and this GET behavior:

```ts
export async function GET({ props }: APIContext<Props>): Promise<Response> {
  const png = await renderOgImage(props.record);
  return new Response(new Uint8Array(png), {
    headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=31536000, immutable' },
  });
}
```

- [ ] **Step 8: Run focused and full frontend tests**

Run:

```powershell
npm.cmd test -- src/lib/og-image.test.ts src/pages/og/og-route.test.ts
npm.cmd test
```

Expected: focused OG tests and the complete Vitest suite PASS.

- [ ] **Step 9: Commit the PNG generation unit**

```powershell
git add -- site/src/lib/og-image.ts site/src/lib/og-image.test.ts 'site/src/pages/og/[id].png.ts' site/src/pages/og/og-route.test.ts
git commit -m "feat: generate summary OG images"
```

### Task 3: Add base-aware OG paths and detail-page metadata

**Files:**
- Modify: `site/src/lib/paths.ts`
- Modify: `site/src/lib/paths.test.ts`
- Modify: `site/src/layouts/BaseLayout.astro`
- Modify: `site/src/pages/summaries/[id].astro`
- Create: `site/src/lib/metadata.test.ts`

**Interfaces:**
- Consumes: summary ID, `import.meta.env.BASE_URL`, and `Astro.site`.
- Produces: `ogImagePath(baseUrl: string, id: string): string` and optional `BaseLayout` metadata props.

- [ ] **Step 1: Write failing path tests**

Extend `paths.test.ts`:

```ts
import { ogImagePath } from './paths';

it('builds an encoded OG image path below the configured base', () => {
  expect(ogImagePath('/AI-Summary/', '中文 id')).toBe('/AI-Summary/og/%E4%B8%AD%E6%96%87%20id.png');
});

it('builds an OG image path for a root deployment', () => {
  expect(ogImagePath('/', 'demo')).toBe('/og/demo.png');
});
```

- [ ] **Step 2: Run path tests and confirm RED**

Run: `npm.cmd test -- src/lib/paths.test.ts`

Expected: FAIL because `ogImagePath` is not exported.

- [ ] **Step 3: Add the minimal path helper**

Add to `paths.ts`:

```ts
export function ogImagePath(baseUrl: string, id: string): string {
  return `${homePath(baseUrl)}og/${encodeURIComponent(id)}.png`;
}
```

- [ ] **Step 4: Run path tests and confirm GREEN**

Run: `npm.cmd test -- src/lib/paths.test.ts`

Expected: all path tests PASS.

- [ ] **Step 5: Write failing source-level metadata contract tests**

Create `site/src/lib/metadata.test.ts` using `readFileSync` to assert that `BaseLayout.astro` declares props named `description`, `canonicalUrl`, `ogImageUrl`, `ogImageAlt`, and `pageType`, and emits all metadata names listed in the approved spec. Assert that `[id].astro` imports `ogImagePath`, constructs URLs from `Astro.site`, passes `record.summary` as description, and passes `record.title` as image alt text.

- [ ] **Step 6: Run metadata tests and confirm RED**

Run: `npm.cmd test -- src/lib/metadata.test.ts`

Expected: FAIL because the layout and detail page do not contain the metadata contract.

- [ ] **Step 7: Implement layout metadata props**

Extend `BaseLayout.astro` props exactly as follows:

```ts
interface Props {
  title: string;
  description?: string;
  canonicalUrl?: string;
  ogImageUrl?: string;
  ogImageAlt?: string;
  pageType?: 'website' | 'article';
}
```

Default description to `AI Digest 的公開內容摘要` and pageType to `website`. Emit canonical only when supplied; emit OG and Twitter image tags only when both `ogImageUrl` and `ogImageAlt` are supplied. Always emit escaped Astro expressions, never `set:html`.

- [ ] **Step 8: Wire absolute detail-page URLs**

In `[id].astro`, require `Astro.site`, create the canonical detail URL with `new URL(summaryPath(baseUrl, record.id), Astro.site)`, create the image URL with `new URL(ogImagePath(baseUrl, record.id), Astro.site)`, and pass title, `record.summary`, both URLs, `pageType="article"`, and image alt equal to `record.title` into `BaseLayout`.

- [ ] **Step 9: Run metadata and full frontend tests**

Run:

```powershell
npm.cmd test -- src/lib/paths.test.ts src/lib/metadata.test.ts
npm.cmd test
```

Expected: focused and full Vitest suites PASS.

- [ ] **Step 10: Commit the metadata unit**

```powershell
git add -- site/src/lib/paths.ts site/src/lib/paths.test.ts site/src/layouts/BaseLayout.astro 'site/src/pages/summaries/[id].astro' site/src/lib/metadata.test.ts
git commit -m "feat: publish summary social metadata"
```

### Task 4: Display OG images on homepage cards

**Files:**
- Modify: `site/src/pages/index.astro`
- Modify: `site/src/styles/global.css`
- Create: `site/src/lib/card-markup.test.ts`

**Interfaces:**
- Consumes: `ogImagePath(baseUrl, record.id)` and existing `summaryPath()`.
- Produces: linked, lazy-loaded homepage card images with stable intrinsic dimensions.

- [ ] **Step 1: Write a failing card markup test**

Create `site/src/lib/card-markup.test.ts` to read `index.astro` and assert the card contains `ogImagePath(baseUrl, record.id)`, `alt={record.title}`, `width="1200"`, `height="630"`, `loading="lazy"`, and `decoding="async"`. Read `global.css` and assert `.summary-card-image` contains `aspect-ratio: 1200 / 630`, `object-fit: cover`, and `width: 100%`.

- [ ] **Step 2: Run the card test and confirm RED**

Run: `npm.cmd test -- src/lib/card-markup.test.ts`

Expected: FAIL because the homepage has no OG image markup.

- [ ] **Step 3: Add linked card image markup**

Import `ogImagePath` beside `summaryPath`. At the start of each card, add a link with the same detail URL as the title and an `<img class="summary-card-image">` carrying all attributes from Step 1. Give the link `aria-label={`閱讀摘要：${record.title}`}` so image and title navigation remain understandable.

- [ ] **Step 4: Add responsive image styling**

Add deterministic card-image styles with zero extra padding around the bitmap, a small border radius, `display: block`, and the exact aspect ratio/object-fit/width contract from Step 1. Preserve the existing card padding and search/sort DOM structure.

- [ ] **Step 5: Run focused and full frontend tests**

Run:

```powershell
npm.cmd test -- src/lib/card-markup.test.ts src/lib/summaries.test.ts
npm.cmd test
```

Expected: all tests PASS; existing reorder tests remain GREEN because `data-summary-card` ownership is unchanged.

- [ ] **Step 6: Commit the card unit**

```powershell
git add -- site/src/pages/index.astro site/src/styles/global.css site/src/lib/card-markup.test.ts
git commit -m "feat: show OG images on summary cards"
```

### Task 5: Extend deployment verification to generated OG assets

**Files:**
- Modify: `scripts/verify_deployment.py`
- Modify: `tests/test_verify_deployment.py`

**Interfaces:**
- Consumes: built `site/dist`, approved base path, local `<img src>`, `og:image`, and `twitter:image` references.
- Produces: deployment violations for missing, malformed, or incorrectly sized local OG PNG files.

- [ ] **Step 1: Write failing verifier tests**

Add tests that create a temporary `dist` containing a detail HTML file referencing `/AI-Summary/og/demo.png`. Cover four cases: missing PNG, wrong PNG signature, valid PNG with dimensions other than 1200 × 630, and a valid 1200 × 630 PNG. Use a tiny helper in the test to construct PNG IHDR bytes with `struct.pack('>II', width, height)`; no Pillow dependency is needed.

- [ ] **Step 2: Run focused verifier tests and confirm RED**

Run from repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verify_deployment.py -q
```

Expected: the new missing/malformed/dimension cases FAIL because generated image references are not inspected.

- [ ] **Step 3: Implement local image-reference and PNG-header verification**

Extend the HTML parser to collect `img src`, `meta[property="og:image"] content`, and `meta[name="twitter:image"] content`. Convert absolute URLs on `yamopeng0918.github.io` and root-relative values under the approved base into paths below `dist_root`; reject path traversal, missing files, non-PNG signatures, truncated IHDR data, and dimensions other than `(1200, 630)`. Ignore external origins and data URLs. Return deterministic violation strings without reading environment variables.

- [ ] **Step 4: Run focused verifier tests and confirm GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_verify_deployment.py -q`

Expected: all deployment-verifier tests PASS.

- [ ] **Step 5: Commit the deployment gate**

```powershell
git add -- scripts/verify_deployment.py tests/test_verify_deployment.py
git commit -m "test: verify generated OG assets"
```

### Task 6: Full build, visual acceptance, and project documentation

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `todo.md`
- Inspect only: `site/dist/og/*.png`

**Interfaces:**
- Consumes: all deliverables from Tasks 1–5.
- Produces: verified Pages artifact, operator documentation, and synchronized project status.

- [ ] **Step 1: Add operator documentation**

Document that `npm.cmd run build:pages` automatically creates one PNG per published summary under `site/dist/og/`, that generated files are build artifacts rather than tracked content, and that font replacement requires an OFL-compatible local TTF plus its license.

- [ ] **Step 2: Run the complete automated gates**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd test
npm.cmd run build:pages
.\.venv\Scripts\python.exe scripts\verify_deployment.py --tracked --dist site\dist --base /AI-Summary/
git diff --check
```

Run the npm commands from `site/`; run Python and Git commands from repository root. Expected: Python and Vitest suites PASS, Astro check reports zero diagnostics, build emits one PNG per published record, deployment verifier exits 0, and `git diff --check` exits 0.

- [ ] **Step 3: Verify artifact count, signatures, dimensions, and metadata references**

Use a read-only script or Sharp metadata inspection to assert:

```text
count(site/dist/og/*.png) == count(loadPublishedSummaries())
every PNG format == png
every PNG width == 1200
every PNG height == 630
every detail page og:image and twitter:image resolves to its PNG
```

Expected: every assertion passes and no archived record has a PNG.

- [ ] **Step 4: Perform visual acceptance on a real Chinese long-title image**

Open the generated PNG for `20260814-always-be-coding-工程師面試必讀-techorange-科技報橘-7374d398` with the local image viewer. Confirm the approved editorial colors, readable Traditional Chinese glyphs, title and two-line summary hierarchy, source/type footer, no overflow, no clipping, and no tofu glyphs.

- [ ] **Step 5: Synchronize project status only after all gates pass**

Add a dated `progress.md` entry containing exact test counts, build result, artifact count, visual inspection result, risks, and next step. Add and check one `todo.md` item for per-summary OG PNG generation, metadata, and card display only if every automated and visual gate passed.

- [ ] **Step 6: Commit the verified documentation unit**

```powershell
git add -- README.md progress.md todo.md
git commit -m "docs: record OG image completion"
```

- [ ] **Step 7: Review final branch state without pushing**

Run:

```powershell
git status --short --branch
git log -6 --oneline
```

Expected: only the user's pre-existing unrelated files remain untracked or modified; the OG implementation commits are local until the user explicitly authorizes a push.
