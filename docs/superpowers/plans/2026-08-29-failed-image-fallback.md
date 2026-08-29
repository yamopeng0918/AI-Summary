# Failed-image Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure a blocked, pending, or failed homepage OG image displays its source fallback instead of broken-image UI.

**Architecture:** Add one focused image-state initializer that owns `pending`, `loaded`, and `failed` transitions. The homepage applies it to every summary image, while CSS shows an image only after a confirmed successful load; images without JavaScript retain existing progressive rendering because the state attribute is added only by the initializer.

**Tech Stack:** Astro 7, TypeScript, Vitest 3, CSS, GitHub Pages, Chrome remote acceptance.

## Global Constraints

- Preserve `loading="lazy"`, image alt text, `object-fit: contain`, source fallback markup, and the approved responsive layout.
- Do not change summary schemas, data, URLs, OG generation, detail pages, parsers, or public interfaces.
- External network access and deployment are not required for routine automated tests.
- Do not push or deploy without explicit user authorization.

---

### Task 1: Implement and test the image-state initializer

**Files:**
- Create: `site/src/lib/summary-image-state.ts`
- Create: `site/src/lib/summary-image-state.test.ts`
- Modify: `site/src/pages/index.astro:93-113`
- Modify: `site/src/styles/global.css:40-43`
- Modify: `site/src/lib/card-markup.test.ts:40-52`

**Interfaces:**
- Consumes: an image-like object with `complete`, `naturalWidth`, `dataset`, and `addEventListener`.
- Produces: `initializeSummaryImage(image): void`, with `data-image-state` values `pending`, `loaded`, or `failed`.

- [ ] **Step 1: Write the failing unit and source-contract tests**

Create `site/src/lib/summary-image-state.test.ts` with a fake image that records `load` and `error` listeners. Assert incomplete images remain `pending`, later `load` becomes `loaded`, cached successful images initialize as `loaded`, later `error` becomes `failed`, and cached completed failures initialize as `failed`.

Update `card-markup.test.ts` to require the initializer import/call and a CSS selector that hides stateful images unless `data-image-state="loaded"`.

```ts
import { describe, expect, it } from 'vitest';
import { initializeSummaryImage, type SummaryImage } from './summary-image-state';

const fakeImage = (complete: boolean, naturalWidth: number) => {
  const listeners = new Map<'load' | 'error', () => void>();
  const image: SummaryImage = {
    complete,
    naturalWidth,
    dataset: {},
    addEventListener: (type, listener) => listeners.set(type, listener),
  };
  return { image, listeners };
};
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run from `site`:

```powershell
npm.cmd test -- src/lib/summary-image-state.test.ts src/lib/card-markup.test.ts
```

Expected: FAIL because `summary-image-state.ts`, the initializer call, and the state visibility CSS do not exist.

- [ ] **Step 3: Add the minimal initializer and integration**

Create `site/src/lib/summary-image-state.ts`:

```ts
export type SummaryImageState = 'pending' | 'loaded' | 'failed';

export type SummaryImage = Pick<HTMLImageElement, 'complete' | 'naturalWidth' | 'dataset'> & {
  addEventListener(
    type: 'load' | 'error',
    listener: () => void,
    options?: AddEventListenerOptions,
  ): void;
};

const setImageState = (image: SummaryImage, state: SummaryImageState) => {
  image.dataset.imageState = state;
};

export const initializeSummaryImage = (image: SummaryImage) => {
  setImageState(image, 'pending');
  image.addEventListener('load', () => setImageState(image, 'loaded'), { once: true });
  image.addEventListener('error', () => setImageState(image, 'failed'), { once: true });
  if (image.complete) setImageState(image, image.naturalWidth > 0 ? 'loaded' : 'failed');
};
```

In `index.astro`, import `initializeSummaryImage` and call it for every `.summary-card-image`. Replace the old `hideBrokenImage` implementation and listeners.

In `global.css`, preserve the current image declaration and add:

```css
.summary-card-image[data-image-state]:not([data-image-state="loaded"]) { visibility: hidden; }
```

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the focused command from Step 2. Expected: both files pass, including all five state transitions and existing markup/layout assertions.

- [ ] **Step 5: Commit the isolated fix**

```powershell
git add -- site/src/lib/summary-image-state.ts site/src/lib/summary-image-state.test.ts site/src/lib/card-markup.test.ts site/src/pages/index.astro site/src/styles/global.css
git commit -m "fix: show source fallback for blocked images"
```

---

### Task 2: Complete local verification and update project status

**Files:**
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: Task 1 implementation and automated tests.
- Produces: verified local build plus an accurate deployment/retest checkpoint.

- [ ] **Step 1: Run the full frontend suite**

Run `npm.cmd test` from `site`. Expected: all Vitest files and tests pass.

- [ ] **Step 2: Run the Pages production build and verifier**

Run `npm.cmd run build:pages` from `site`. Expected: Astro check reports 0 errors, the static build completes, and deployment verification exits 0.

- [ ] **Step 3: Run safety and whitespace verification**

From the repository root, run:

```powershell
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
git diff --check
```

Expected: both commands exit 0 with no sensitive-data or whitespace failures.

- [ ] **Step 4: Record verified local status without claiming remote success**

Update `progress.md` with the state model and exact test/build totals. Update `todo.md` to mark the local fix verified while keeping deployment and Chrome remote retest unchecked.

- [ ] **Step 5: Commit the verification record**

```powershell
git add -- progress.md todo.md
git commit -m "docs: record blocked-image fallback verification"
```

---

### Task 3: Deploy and repeat Chrome failed-image acceptance

**Files:**
- Modify after successful remote verification: `progress.md`
- Modify after successful remote verification: `todo.md`

**Interfaces:**
- Consumes: explicit user authorization to push, the verified Task 2 commit, and Chrome with the ChatGPT Browser Extension.
- Produces: successful Pages workflow evidence and a remote screenshot/state audit with images blocked.

- [ ] **Step 1: Obtain explicit push authorization**

Do not push or deploy until the user explicitly authorizes uploading the verified commits to `origin/master`.

- [ ] **Step 2: Push and monitor Pages**

Run `git push origin master`. Expected: `origin/master` advances to the verified local head and the matching Deploy to GitHub Pages run completes successfully.

- [ ] **Step 3: Verify normal-image state in Chrome**

With images allowed, open the public Pages homepage and confirm all seven images reach `data-image-state="loaded"`, have `naturalWidth=1200`, use `object-fit: contain`, and render without horizontal overflow.

- [ ] **Step 4: Verify blocked-image fallback in Chrome**

Temporarily block images for the Pages origin and reload. Confirm all seven images remain `pending` or become `failed`, are visually hidden, all seven source fallbacks are visible, no broken icon/alt text is rendered, and no horizontal overflow occurs. Capture a viewport screenshot, then restore image permission to default and reload.

- [ ] **Step 5: Record remote acceptance**

Only after Steps 2-4 pass, mark the remote failed-image item complete in `progress.md` and `todo.md`, run `git diff --check`, commit the documentation, and request separate authorization before pushing that documentation commit.
