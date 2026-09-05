# AI Digest Closure PowerPoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a nine-slide, 16:9 AI Digest closure-report PowerPoint with Traditional Chinese speaker notes for a 5–7 minute presentation.

**Architecture:** A single JavaScript ES module uses `@oai/artifact-tool` to assemble the deck from repository evidence and locally captured product screenshots. Content constants, layout helpers, source-note helpers, and slide builders remain separate functions in the same temporary builder so every slide is deterministic and editable. The final PPTX is rendered slide-by-slide and revised until visual and overflow checks pass.

**Tech Stack:** JavaScript ES modules, `@oai/artifact-tool`, PowerPoint `.pptx`, bundled presentation render/QA tools, repository JSON/Markdown evidence, local browser screenshots.

## Global Constraints

- Follow `docs/superpowers/specs/2026-09-05-ai-digest-closure-powerpoint-design.md` exactly.
- Output exactly one editable 16:9 PPTX at `deliverables/AI_Digest_結案報告.pptx`.
- Use nine slides and Traditional Chinese audience-facing copy.
- Include Traditional Chinese speaker notes on every slide; total speaking time must fit 5–7 minutes.
- Use the explicit AI Digest custom visual direction: warm white, deep ink green/near-black, coral accent, editorial technology-product styling.
- Use repository and verified deployment evidence only; do not describe PDF, OCR, login/private content, full threads, admin UI, or multi-user accounts as complete.
- Never expose API keys, tokens, cookies, `.env` values, or private paths.
- Every external asset and non-trivial external claim must have a `[Sources]` block in the corresponding slide notes.
- Do not deliver any slide with unintended overlap, clipping, overflow, broken wrapping, or unreadable image crops.

---

### Task 1: Establish the evidence and asset package

**Files:**
- Create: `.artifacts/ai-digest-closure-powerpoint/source-notes.txt`
- Create: `.artifacts/ai-digest-closure-powerpoint/content-outline.txt`
- Create: `.artifacts/ai-digest-closure-powerpoint/assets/homepage.png`
- Create: `.artifacts/ai-digest-closure-powerpoint/assets/web-summary.png`
- Create: `.artifacts/ai-digest-closure-powerpoint/assets/youtube-summary.png`
- Create: `.artifacts/ai-digest-closure-powerpoint/assets/bluesky-summary.png`
- Read: `progress.md`
- Read: `todo.md`
- Read: `data/classifier/evaluation.json`
- Read: `data/summaries/*.json`

**Interfaces:**
- Consumes: verified project status, classifier evaluation, published summary records, public GitHub Pages UI.
- Produces: four safe local screenshots and a source ledger used by the deck builder.

- [ ] **Step 1: Create a clean temporary build directory**

Create `.artifacts/ai-digest-closure-powerpoint/` and keep all intermediate files beneath it. Record the presentation skill path, temporary directory, and final PPTX path as command-scoped absolute paths during execution.

- [ ] **Step 2: Record the evidence ledger**

Write `source-notes.txt` with these exact evidence mappings:

```text
Slides 1–6, 8–9: progress.md; project scope, three-source MVP, architecture, tests, deployment acceptance.
Slide 4: docs/superpowers/specs/2026-08-09-ai-digest-mvp-design.md; approved pipeline and component boundaries.
Slide 5: data/summaries/*.json and public GitHub Pages; published source examples and UI screenshots.
Slide 7: data/classifier/evaluation.json; 180 reviewed rows, Accuracy 0.9167, Macro F1 0.9179, majority baseline 0.1667.
Slide 9: progress.md; 715 passed, 2 skipped, Vitest 67 passed, Astro build and deployment verification.
```

- [ ] **Step 3: Capture safe product screenshots**

Capture the public homepage plus representative web, YouTube, and Bluesky detail pages. Use only public content, crop out browser chrome when it adds no value, and verify no secret, cookie, local path, or account detail appears.

- [ ] **Step 4: Write the exact nine-slide content outline**

Write `content-outline.txt` with these slide titles in order:

```text
1 AI Digest
2 資訊很多，但知識沒有被整理
3 從一次摘要，做到完整產品流程
4 三種來源，一條可驗證的處理主幹
5 一般網頁、YouTube、Bluesky 都能落地
6 清楚分工，讓每個環節可獨立驗證
7 分類成果不只靠感覺
8 跨來源整合，是最大的工程挑戰
9 從功能完成，到可重現、可驗證、可部署
```

- [ ] **Step 5: Verify the package**

Run read-only checks confirming all four images exist, each image opens correctly, `evaluation.json` still contains `accepted: true`, and every visible number in the outline matches repository evidence.

---

### Task 2: Build the editable nine-slide deck

**Files:**
- Create: `.artifacts/ai-digest-closure-powerpoint/build-deck.mjs`
- Create: `deliverables/AI_Digest_結案報告.pptx`
- Read: presentation skill `style_guidelines.md`
- Read: presentation skill `artifact_tool_docs/API_QUICK_START.md`
- Read: presentation skill `artifact_tool_docs/api/API_DOCS.md`

**Interfaces:**
- Consumes: Task 1 screenshots, content outline, evidence ledger, and repository fonts at `site/src/assets/fonts/`.
- Produces: a nine-slide editable PPTX with slide notes and `[Sources]` blocks.

- [ ] **Step 1: Load the approved presentation runtime**

Call `load_workspace_dependencies`, use its exact `RUNTIME_NODE`, `RUNTIME_NODE_MODULES`, and `RUNTIME_BIN_DIR` values, and create the required `node_modules` junction in the temporary directory. Do not install or derive alternate dependencies.

- [ ] **Step 2: Mark the create operation exactly once**

From the presentation skill directory run:

```text
node container_tools/mark_artifact_operation_started.mjs --operation-kind create --expected-output-count 1 --output-format pptx
```

Expected: exit code 0 before the first authoring command.

- [ ] **Step 3: Define the deck design system**

In `build-deck.mjs`, define reusable constants and helpers with these responsibilities:

```js
const COLORS = {
  paper: "F4EFE5",
  cream: "E7DED0",
  ink: "211D19",
  green: "193D31",
  coral: "A33B2B",
  mint: "DCF1EA",
  white: "FFFFFF",
};

function addSlideTitle(slide, index, title) { /* fixed title and page marker */ }
function addSourceNotes(slide, body, sources) { /* speaker script plus [Sources] block */ }
function addFooter(slide, index) { /* consistent AI Digest footer */ }
function addMetric(slide, x, y, value, label, color) { /* editable large-number treatment */ }
function addImageCrop(slide, imagePath, frame) { /* proportional crop with no distortion */ }
```

Use the bundled Noto Serif CJK TC files for reliable Traditional Chinese rendering. Keep title text at least 35 pt, cover title at least 50 pt, mid-level text at least 24 pt, and body text at least 16 pt.

- [ ] **Step 4: Implement slides 1–3**

Build a minimal cover, a problem framing slide, and a product-result overview. Use `homepage.png` only on the cover or result overview, not both. Speaker notes should total about 90 seconds and introduce the project without implementation detail overload.

- [ ] **Step 5: Implement slides 4–6**

Build the three-source pipeline, real source-result comparison, and architecture slide. On slide 4, create connectors before nodes and show source-specific extraction merging into one validated pipeline. On slide 5, use the three distinct screenshots once each. On slide 6, show Python CLI, independent extractors, summary/classifier boundaries, validated JSON, and Astro as a flat layered architecture.

- [ ] **Step 6: Implement slides 7–9**

Build the classifier evidence slide using editable large numbers, the challenge/solution slide using three concise paired statements, and the final verification/learning slide. Slide 9 must distinguish completed MVP items from excluded optional scope.

- [ ] **Step 7: Add complete speaker notes**

Give every slide a 35–55 second Traditional Chinese script, except the cover at 20–25 seconds. Each note must add spoken context rather than repeat slide text verbatim, and end with a `[Sources]` block listing repository-relative files or the public Pages URL used on that slide.

- [ ] **Step 8: Export the PPTX**

Run `build-deck.mjs` with the approved runtime and export exactly:

```text
deliverables/AI_Digest_結案報告.pptx
```

Expected: one non-empty `.pptx` containing nine slides.

---

### Task 3: Render and visually review every slide

**Files:**
- Create: `.artifacts/ai-digest-closure-powerpoint/rendered/slide-1.png` through `slide-9.png`
- Create: `.artifacts/ai-digest-closure-powerpoint/montage.png`
- Modify: `.artifacts/ai-digest-closure-powerpoint/build-deck.mjs`
- Regenerate: `deliverables/AI_Digest_結案報告.pptx`

**Interfaces:**
- Consumes: Task 2 PPTX.
- Produces: visually reviewed PPTX with no unintended overlap or clipping.

- [ ] **Step 1: Render all slides**

Use `container_tools/render_slides.py` on the final PPTX and verify exactly nine PNG files are produced.

- [ ] **Step 2: Create and inspect the montage**

Use `container_tools/create_montage.py` and inspect deck-level rhythm, color consistency, slide variety, margins, and repeated imagery.

- [ ] **Step 3: Inspect every slide individually**

Open all nine slide PNGs at full size. Record each issue in `.artifacts/ai-digest-closure-powerpoint/qa-ledger.txt` with slide number and one of: overlap, clipping, wrapping, crop, contrast, alignment, density, or factual mismatch.

- [ ] **Step 4: Fix every recorded issue**

Update only the relevant layout or copy in `build-deck.mjs`, regenerate the PPTX, rerender all slides, and re-inspect the changed slides plus the montage. Repeat until the QA ledger has no open issue.

- [ ] **Step 5: Run automated overflow validation**

Run:

```text
python container_tools/slides_test.py deliverables/AI_Digest_結案報告.pptx
```

Expected: exit code 0 and no slide element outside the original canvas.

---

### Task 4: Verify evidence, notes, and project records

**Files:**
- Modify: `progress.md`
- Modify: `todo.md`
- Verify: `deliverables/AI_Digest_結案報告.pptx`

**Interfaces:**
- Consumes: visually approved Task 3 deck and repository evidence.
- Produces: final recorded deliverable with reproducible verification evidence.

- [ ] **Step 1: Inspect the final deck structure**

Confirm nine slides, 16:9 dimensions, editable text/shapes, notes on all nine slides, and a `[Sources]` block on every slide that contains external assets or non-trivial claims.

- [ ] **Step 2: Verify the speaking-time budget**

Count the Traditional Chinese speaker-note characters and verify the scripts fit 5–7 minutes at a natural presentation pace. Shorten repetition before altering the approved narrative.

- [ ] **Step 3: Reconcile every numeric claim**

Compare slides 7 and 9 against `data/classifier/evaluation.json` and `progress.md`. Required values are 180 reviewed rows, Accuracy 0.9167, Macro F1 0.9179, majority baseline 0.1667, Python 715 passed/2 skipped, and Vitest 67 passed.

- [ ] **Step 4: Scan the final package for sensitive content**

Check visible slide text, notes, screenshots, and the final PPTX package for API-key patterns, tokens, cookies, `.env` values, and private local paths. Expected: no sensitive match.

- [ ] **Step 5: Update project progress**

Add a dated `2026-09-05` entry to `progress.md` describing the verified nine-slide PPTX, speaker notes, render review, overflow result, and output path. Add a checked PowerPoint deliverable item to `todo.md`; do not mark the former full video as complete.

- [ ] **Step 6: Run final repository checks**

Run `git diff --check`, verify the PPTX opens and renders again from the final path, and inspect `git status` so only intended PowerPoint source/output and progress files are included.

- [ ] **Step 7: Commit the verified work unit**

Stage only the intended presentation deliverable and progress records, then commit with:

```text
git commit -m "docs: add AI Digest closure presentation"
```

Do not push, open a pull request, or deploy without a separate explicit user instruction.
