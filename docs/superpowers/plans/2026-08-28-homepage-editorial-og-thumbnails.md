# Homepage Editorial OG Thumbnails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 AI Digest 正式首頁改為已核准的 A「編輯雜誌風」，並讓所有 OG 圖以完整縮圖呈現而不裁切。

**Architecture:** 保留現有 Astro 靜態資料載入、搜尋、分類、排序及路徑函式，只調整首頁語意標記與全域樣式。最新的 `published` 摘要仍是 `#summary-list` 中唯一的一份卡片節點，以 `summary-card--featured` 呈現精選版型；既有重排程式繼續操作同一批 `data-summary-card` 節點，因此不複製資料，也不改變篩選結果。

**Tech Stack:** Astro 7、TypeScript、CSS、Vitest 3、Node.js 22.12+

## Global Constraints

- OG 圖展示框固定使用 `aspect-ratio: 1200 / 630`，圖片必須使用 `object-fit: contain`，禁止裁切、拉伸或變形。
- 桌面摘要卡片為三欄、平板兩欄、手機單欄；精選卡片在桌面跨滿欄位並採文字／圖片雙欄，小螢幕改為單欄。
- 搜尋、分類篩選、日期排序與無結果狀態必須維持現有行為。
- Astro 只讀取已驗證且狀態為 `published` 的資料；不得修改摘要 Schema、JSON、CLI 或後端流程。
- 不新增前端 API、密鑰、後端服務、外部字型服務或 npm dependency。
- 卡片主要連結必須可透過鍵盤聚焦，焦點狀態清楚可見；OG 圖替代文字使用摘要標題。
- 使用暖白背景、深墨文字與磚紅重點色；標題採既有本機／系統襯線字體，介面與內文採系統無襯線字體。
- 實作必須遵循 TDD：先確認新測試因缺少行為而失敗，再寫最小正式程式。

---

## File Structure

- `site/src/lib/card-markup.test.ts`：以靜態原始碼契約驗證首頁精選標記、單一可聚焦卡片連結、OG 圖載入屬性與完整縮圖 CSS。
- `site/src/pages/index.astro`：建立編輯雜誌風首頁語意結構；最新摘要加上精選 class，所有摘要仍保留相同 `data-summary-card` 節點與既有篩選腳本。
- `site/src/styles/global.css`：定義色彩、字體、精選雙欄、三／二／一欄卡片、完整 OG 縮圖、hover／focus、fallback 背景及響應式規則。
- `progress.md`：記錄已實作、驗證結果、風險與下一步。
- `todo.md`：新增並只勾選已通過驗證的首頁編輯雜誌風工作項目。

### Task 1: Editorial homepage markup and complete OG thumbnails

**Files:**
- Modify: `site/src/lib/card-markup.test.ts`
- Modify: `site/src/pages/index.astro`
- Modify: `site/src/styles/global.css`

**Interfaces:**
- Consumes: `loadPublishedSummaries(): SummaryRecord[]`, `summaryPath(baseUrl: string, id: string): string`, `ogImagePath(baseUrl: string, id: string): string`, and the existing `data-summary-card`/`reorderSummaryCards` DOM contract.
- Produces: `.summary-card--featured` on exactly the first sorted published record; `.summary-card-link` as the one keyboard-focusable wrapper per card; `.summary-card-image-frame` with a source fallback label; responsive CSS whose image rule uses `object-fit: contain`.

- [ ] **Step 1: Replace the existing card source-contract tests with failing editorial-layout tests**

Update `site/src/lib/card-markup.test.ts` to:

```ts
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

const homepageSource = readFileSync(new URL('../pages/index.astro', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../styles/global.css', import.meta.url), 'utf8');

describe('editorial homepage cards', () => {
  it('marks only the newest published record as the featured card', () => {
    expect(homepageSource).toContain('summaries.map((record, index) =>');
    expect(homepageSource).toContain("index === 0 && 'summary-card--featured'");
    expect(homepageSource).toContain('data-summary-card={record.id}');
  });

  it('renders one keyboard-focusable card link with a labelled OG image', () => {
    for (const markup of [
      "import { ogImagePath, summaryPath } from '../lib/paths';",
      'class="summary-card-link"',
      'href={summaryPath(baseUrl, record.id)}',
      'src={ogImagePath(baseUrl, record.id)}',
      'alt={record.title}',
      'width="1200"',
      'height="630"',
      'loading={index === 0 ? \'eager\' : \'lazy\'}',
      'decoding="async"',
      'class="summary-card-image-fallback"',
    ]) {
      expect(homepageSource).toContain(markup);
    }
  });

  it('contains OG images without cropping or distortion', () => {
    expect(globalStyles).toMatch(/\.summary-card-image-frame\s*\{[^}]*aspect-ratio:\s*1200\s*\/\s*630[^}]*\}/);
    expect(globalStyles).toMatch(/\.summary-card-image\s*\{[^}]*height:\s*100%[^}]*object-fit:\s*contain[^}]*width:\s*100%[^}]*\}/);
    expect(globalStyles).not.toMatch(/\.summary-card-image\s*\{[^}]*object-fit:\s*cover[^}]*\}/);
  });

  it('defines featured, three-column, tablet, and mobile layouts', () => {
    expect(globalStyles).toMatch(/\.summary-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)[^}]*\}/);
    expect(globalStyles).toMatch(/\.summary-card--featured\s*\{[^}]*grid-column:\s*1\s*\/\s*-1[^}]*\}/);
    expect(globalStyles).toMatch(/@media\s*\(max-width:\s*56rem\)[\s\S]*?\.summary-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    expect(globalStyles).toMatch(/@media\s*\(max-width:\s*42rem\)[\s\S]*?\.summary-grid\s*\{[^}]*grid-template-columns:\s*1fr/);
  });
});
```

- [ ] **Step 2: Run the focused tests and verify the new contract fails**

Run:

```powershell
Set-Location site
npm.cmd test -- src/lib/card-markup.test.ts
```

Expected: FAIL because `index === 0`, `.summary-card--featured`, `.summary-card-image-frame`, `object-fit: contain`, and the explicit three-column responsive rules do not yet exist; the old stylesheet still contains `object-fit: cover`.

- [ ] **Step 3: Implement the minimal editorial card markup**

In `site/src/pages/index.astro`, keep the imports, data loading, filters, empty states, serialized records, and existing client script unchanged. Replace only the current `summaries.map((record) => (...))` card block with:

```astro
{summaries.map((record, index) => (
  <article
    class:list={['summary-card', index === 0 && 'summary-card--featured']}
    data-summary-card={record.id}
  >
    <a class="summary-card-link" href={summaryPath(baseUrl, record.id)} aria-label={`閱讀摘要：${record.title}`}>
      <div class="summary-card-image-frame">
        <span class="summary-card-image-fallback" aria-hidden="true">
          {record.author ?? (record.sourceType === 'youtube' ? 'YouTube' : record.sourceType === 'social' ? '社群貼文' : '公開網頁')}
        </span>
        <img
          class="summary-card-image"
          src={ogImagePath(baseUrl, record.id)}
          alt={record.title}
          width="1200"
          height="630"
          loading={index === 0 ? 'eager' : 'lazy'}
          decoding="async"
        />
      </div>
      <div class="summary-card-content">
        {index === 0 && <p class="featured-label">本期精選</p>}
        <div class="card-meta">
          <span>{record.category}</span>
          <time datetime={record.createdAt}>{record.createdAt.slice(0, 10)}</time>
        </div>
        <h2>{record.title}</h2>
        <p class="card-summary">{record.summary}</p>
        <ul class="tag-list" aria-label="標籤">
          {record.tags.map((tag) => <li>{tag}</li>)}
        </ul>
        <span class="card-cta">閱讀完整摘要<span aria-hidden="true"> →</span></span>
      </div>
    </a>
  </article>
))}
```

This preserves one DOM node per summary and keeps every card in the existing `#summary-list` reorder/filter contract. The fallback label sits behind the image and becomes visible if the image cannot paint; it is `aria-hidden` because the image already has meaningful alternative text.

- [ ] **Step 4: Implement the minimal editorial CSS**

In `site/src/styles/global.css`:

1. Change the `:root` palette and add the editorial font variables:

```css
:root {
  --paper: #f4efe5;
  --surface: #fffaf0;
  --ink: #211d19;
  --muted: #6c6259;
  --line: #cfc3b4;
  --accent: #a33b2b;
  color: var(--ink);
  background: var(--paper);
  font-family: "Noto Sans TC", system-ui, sans-serif;
  line-height: 1.65;
}
```

2. Change link and focus colors to the approved palette:

```css
a { color: var(--accent); }
a:focus-visible, input:focus-visible, select:focus-visible {
  outline: 3px solid var(--accent);
  outline-offset: 3px;
}
```

3. Give homepage and detail headings the local/system serif stack without adding a dependency:

```css
.page-intro h1, .detail h1, .summary-card h2 {
  font-family: "Noto Serif TC", "PMingLiU", Georgia, serif;
}
```

4. Replace the existing `.summary-grid` through `.card-link` homepage card rules with:

```css
.summary-grid {
  display: grid;
  gap: 1.5rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.summary-card {
  background: var(--surface);
  border: 1px solid var(--line);
  min-width: 0;
  transition: border-color 160ms ease, transform 160ms ease;
}
.summary-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.summary-card-link { color: inherit; display: flex; flex-direction: column; height: 100%; text-decoration: none; }
.summary-card-link:focus-visible { outline: 3px solid var(--accent); outline-offset: 4px; }
.summary-card-image-frame {
  aspect-ratio: 1200 / 630;
  background: #e7ded0;
  display: grid;
  overflow: hidden;
  place-items: center;
  position: relative;
}
.summary-card-image-fallback {
  color: var(--muted);
  font-size: .82rem;
  font-weight: 700;
  inset: 0;
  letter-spacing: .08em;
  padding: 1rem;
  position: absolute;
  text-align: center;
}
.summary-card-image {
  background: #e7ded0;
  display: block;
  height: 100%;
  object-fit: contain;
  position: relative;
  width: 100%;
}
.summary-card-content { display: flex; flex: 1; flex-direction: column; padding: 1.25rem; }
.summary-card h2 { font-size: 1.35rem; line-height: 1.35; margin: .65rem 0; }
.card-summary { color: var(--muted); flex-grow: 1; margin: 0 0 1rem; }
.card-meta { color: var(--muted); display: flex; font-size: .85rem; gap: .5rem; justify-content: space-between; }
.featured-label { color: var(--accent); font-size: .78rem; font-weight: 800; letter-spacing: .12em; margin: 0 0 .5rem; text-transform: uppercase; }
.tag-list { display: flex; flex-wrap: wrap; gap: .45rem; list-style: none; margin: 0 0 1rem; padding: 0; }
.tag-list li { border: 1px solid var(--line); color: var(--accent); font-size: .78rem; padding: .12rem .5rem; }
.card-cta, .back-link { color: var(--accent); font-weight: 800; text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: .18em; }
.summary-card--featured { grid-column: 1 / -1; }
.summary-card--featured .summary-card-link { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr); }
.summary-card--featured .summary-card-image-frame { grid-column: 2; grid-row: 1; }
.summary-card--featured .summary-card-content { grid-column: 1; grid-row: 1; justify-content: center; padding: clamp(1.5rem, 4vw, 3.5rem); }
.summary-card--featured h2 { font-size: clamp(1.9rem, 4vw, 3.2rem); }
```

5. Add the tablet breakpoint before the existing `42rem` breakpoint:

```css
@media (max-width: 56rem) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-card--featured .summary-card-link { grid-template-columns: 1fr; }
  .summary-card--featured .summary-card-image-frame,
  .summary-card--featured .summary-card-content { grid-column: 1; }
  .summary-card--featured .summary-card-image-frame { grid-row: 1; }
  .summary-card--featured .summary-card-content { grid-row: 2; }
}
```

6. Add this rule inside the existing `@media (max-width: 42rem)` block:

```css
.summary-grid { grid-template-columns: 1fr; }
```

Keep the detail-page rules intact. Where old color literals are shared by homepage/detail styles, retain them unless the selector is explicitly replaced above; this prevents an unrelated detail-page redesign.

- [ ] **Step 5: Run the focused tests and verify they pass**

Run:

```powershell
Set-Location site
npm.cmd test -- src/lib/card-markup.test.ts
```

Expected: `4 passed` and exit code 0.

- [ ] **Step 6: Run all frontend tests and the production build**

Run:

```powershell
Set-Location site
npm.cmd test
npm.cmd run build
```

Expected: every Vitest test passes; `astro check` reports 0 errors; `astro build` completes successfully and emits the homepage, detail pages, and OG routes.

- [ ] **Step 7: Inspect responsive rendering in a browser**

Run:

```powershell
Set-Location site
npm.cmd run dev -- --host 127.0.0.1
```

Open the local homepage and inspect at widths 1280 px, 800 px, and 390 px. Confirm:

- 1280 px: latest record is one full-width, two-column featured card; following records form three columns.
- 800 px: featured card is stacked; following records form two columns.
- 390 px: all cards form one column and no horizontal scrolling occurs.
- Every OG image is completely visible with letterboxing where necessary; no image uses crop or stretch.
- Tab reaches each card once and the brick-red focus outline is visible.
- Search, category, newest/oldest order, and the no-results message still work.
- Simulating a failed OG request exposes the source fallback label without collapsing the fixed image area.

Stop the development server after inspection.

- [ ] **Step 8: Check the diff and commit the independently testable homepage change**

Run:

```powershell
git diff --check
git diff -- site/src/lib/card-markup.test.ts site/src/pages/index.astro site/src/styles/global.css
git status --short
git add -- site/src/lib/card-markup.test.ts site/src/pages/index.astro site/src/styles/global.css
git commit -m "feat: add editorial homepage thumbnail layout"
```

Expected: `git diff --check` emits no errors; the diff contains only the tested homepage files; the commit succeeds without adding unrelated untracked files.

### Task 2: Progress documentation and final verification

**Files:**
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: the verified Task 1 commit and its exact Vitest/Astro/build results.
- Produces: project records that distinguish completed local implementation from any unperformed GitHub push or remote Pages acceptance.

- [ ] **Step 1: Record the verified deliverable in `progress.md`**

Append this section after copying the exact pass counts into the command log or commit message:

```markdown
### 首頁編輯雜誌風與完整 OG 縮圖（2026-08-28）

- 已依核准規格完成 A「編輯雜誌風」正式首頁：最新摘要使用精選版型，其他摘要在桌面／平板／手機分別呈現三／二／一欄。
- 首頁所有 OG 圖固定為 `1200:630` 展示框並使用 `object-fit: contain`，完整呈現且不裁切、不拉伸。
- 搜尋、分類篩選、日期排序、無結果狀態、鍵盤焦點與圖片失敗占位均已在本機驗收。
- 前端驗證通過：focused Vitest **4 passed**；完整 Vitest 全數通過；Astro check **0 errors**；正式建置成功。完整測試數以本次驗證輸出為準。
- 尚未執行 GitHub push、Pages workflow 或遠端視覺驗收；不得將遠端部署標記為完成。
```

- [ ] **Step 2: Add a completed, evidence-scoped checklist section to `todo.md`**

Append:

```markdown
## 首頁編輯雜誌風與完整 OG 縮圖（2026-08-28）

- [x] 將最新已發布摘要呈現為編輯雜誌風精選卡片，並維持所有摘要共用既有搜尋、分類及排序流程。
- [x] 首頁 OG 圖使用固定 `1200:630` 展示框與 `object-fit: contain`，不裁切、不拉伸。
- [x] 完成三／二／一欄響應式排版、可見鍵盤焦點與圖片失敗占位。
- [x] 通過相關 Vitest、完整前端測試、Astro check、正式建置及本機瀏覽器驗收。
- [ ] 執行 GitHub push、Pages workflow 與遠端首頁視覺驗收。
```

- [ ] **Step 3: Run final verification from a clean command sequence**

Run:

```powershell
Set-Location site
npm.cmd test
npm.cmd run build:pages
Set-Location ..
git diff --check
git status --short
```

Expected: all Vitest tests pass; Astro check reports 0 errors; Pages production build and `verify_deployment.py` pass; `git diff --check` emits no output; only `progress.md` and `todo.md` plus pre-existing unrelated untracked files remain outside the Task 1 commit.

- [ ] **Step 4: Review documentation consistency**

Run:

```powershell
rg -n "首頁編輯雜誌風|object-fit: contain|遠端" progress.md todo.md docs/superpowers/specs/2026-08-28-homepage-editorial-og-thumbnails-design.md
```

Expected: the implementation, verification, and remote-deployment status agree across all three documents; no document claims that push or Pages acceptance occurred.

- [ ] **Step 5: Commit only the progress records**

Run:

```powershell
git add -- progress.md todo.md
git commit -m "docs: record editorial homepage progress"
git status --short
```

Expected: the commit contains only `progress.md` and `todo.md`; unrelated pre-existing untracked files remain unmodified and uncommitted.
