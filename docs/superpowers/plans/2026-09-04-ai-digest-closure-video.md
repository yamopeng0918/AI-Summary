# AI Digest Closure Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and verify a 5–7 minute, 1920×1080 Hyperframes closure-report video that presents AI Digest’s complete product flow and cross-source development journey to course instructors and reviewers.

**Architecture:** Treat the video as a traceable editorial pipeline: an evidence manifest constrains claims, a narration script establishes timing, a shot list maps every sentence to visuals, approved captures supply source material, and Hyperframes assembles the final composition. Keep editable production documents in Git, keep credentials and private browser state out of all artifacts, and do not commit a large rendered MP4 unless the user separately approves it.

**Tech Stack:** Markdown production documents, AI Digest repository evidence, browser-safe screenshots or screen recordings, Hyperframes, Traditional Chinese narration and subtitles, MP4/H.264 at 1920×1080.

## Global Constraints

- Runtime must be 5–7 minutes, targeting approximately 6 minutes.
- The presentation must be approximately 60% product results and 40% learning journey.
- The audience is course instructors and reviewers; tone is a concise technology product presentation.
- The main story is the complete path from public URL input to extraction/transcript, structured summary, classification, validated JSON, GitHub Pages build, and deployment.
- Web, YouTube, and Bluesky must appear as branches that rejoin one shared pipeline.
- Claims and metrics must come from tracked repository evidence; optional PDF/OCR/login/private-thread/admin features must not be presented as complete.
- No API key, token, cookie, `.env` content, private browser data, or sensitive local path may appear in scripts, captures, logs, or exports.
- Final output must be 16:9, 1920×1080 MP4 with Traditional Chinese narration and subtitles.

---

### Task 1: Evidence manifest and editorial claim gate

**Files:**
- Create: `docs/video/ai-digest-closure-evidence.md`
- Read: `progress.md`
- Read: `todo.md`
- Read: `README.md`
- Read: `data/classifier/evaluation.json`

**Interfaces:**
- Consumes: approved design and current tracked project evidence.
- Produces: one source-of-truth table with `claim`, `exact value`, `source path`, `allowed wording`, and `visual treatment` columns.

- [ ] **Step 1: Record the required verified claims**

Include the three supported sources, the end-to-end pipeline, 180 reviewed records, Accuracy `0.9167`, Macro F1 `0.9179`, majority baseline `0.1667`, current test/build evidence, and successful GitHub Pages deployment. Mark all optional features explicitly out of scope.

- [ ] **Step 2: Cross-check every number against its tracked source**

Run:

```powershell
rg -n "0\.9167|0\.9179|0\.1667|715 passed|67 passed|三來源|GitHub Pages" progress.md todo.md README.md data/classifier
```

Expected: every number and completion claim in the manifest has at least one matching tracked source; no unsupported number remains.

- [ ] **Step 3: Scan for prohibited claims and secrets**

Run:

```powershell
rg -n "已完成.*(PDF|OCR|登入|私人|後台|多使用者)|API[_ -]?KEY|TOKEN|COOKIE|\.env" docs/video/ai-digest-closure-evidence.md
```

Expected: no secret value; optional features appear only as explicitly excluded scope.

- [ ] **Step 4: Commit the evidence manifest**

```powershell
git add -- docs/video/ai-digest-closure-evidence.md
git diff --cached --check
git commit -m "docs: establish closure video evidence"
```

### Task 2: Timed Traditional Chinese narration

**Files:**
- Create: `docs/video/ai-digest-closure-narration.md`
- Read: `docs/video/ai-digest-closure-evidence.md`
- Read: `docs/superpowers/specs/2026-09-04-ai-digest-closure-video-design.md`

**Interfaces:**
- Consumes: only wording and figures allowed by the evidence manifest.
- Produces: six timestamped narration sections totaling approximately 1,500–1,900 Traditional Chinese characters, ready for recording or text-to-speech.

- [ ] **Step 1: Draft the six narration sections**

Write sections for problem/goal, complete flow, three-source proof, technical evidence, cross-source challenge, and conclusion. Open with the user problem, explain the shared pipeline before implementation details, and close by distinguishing the completed MVP from optional scope.

- [ ] **Step 2: Add spoken-time budgets**

Assign each paragraph a start/end timestamp and ensure the total target is about `06:00`, with the final acceptable range `05:00–07:00`.

- [ ] **Step 3: Perform wording and evidence checks**

Run:

```powershell
rg -n "0\.9167|0\.9179|0\.1667|715|67|180" docs/video/ai-digest-closure-narration.md
rg -n "革命性|百分之百|完全取代|零錯誤|全自動萬能" docs/video/ai-digest-closure-narration.md
```

Expected: required evidence appears with exact values; no exaggerated phrase is present.

- [ ] **Step 4: Read the narration aloud and revise for natural speech**

Expected: no sentence requires displaying source code to be understood, acronyms are explained on first use, and the spoken draft fits 5–7 minutes at a calm presentation pace.

- [ ] **Step 5: Commit the narration**

```powershell
git add -- docs/video/ai-digest-closure-narration.md
git diff --cached --check
git commit -m "docs: script closure video narration"
```

### Task 3: Shot list and visual system

**Files:**
- Create: `docs/video/ai-digest-closure-storyboard.md`
- Create: `docs/video/ai-digest-closure-style-guide.md`
- Read: `docs/video/ai-digest-closure-narration.md`

**Interfaces:**
- Consumes: timestamped narration.
- Produces: a shot-by-shot table with `time`, `narration`, `visual`, `screen text`, `motion`, `asset`, and `evidence` fields, plus reusable color/type/motion rules.

- [ ] **Step 1: Divide narration into 8–12 second shots**

Each shot must communicate one idea. Use longer 15–20 second shots only for the complete pipeline demonstration or a legible product walkthrough.

- [ ] **Step 2: Define the visual grammar**

Specify a dark technology background, one accent color sampled from the current AI Digest site, high-contrast Traditional Chinese typography, consistent data cards, restrained transitions, and subtitle safe areas. Specify that code blocks and terminal logs may appear only as brief proof details, never as the main visual.

- [ ] **Step 3: Map the shared pipeline visually**

Create one recurring flow: `公開網址 → 來源辨識 → 文字／逐字稿 → AI 摘要 → 分類 → Schema 驗證 → JSON → GitHub Pages`. Branch the three source types only during extraction and merge them before summarization.

- [ ] **Step 4: Validate shot coverage**

Expected: every narration paragraph maps to at least one shot; every quantitative claim has a corresponding evidence card; total shot durations equal narration duration; no shot requests an unavailable or sensitive asset.

- [ ] **Step 5: Commit storyboard and style guide**

```powershell
git add -- docs/video/ai-digest-closure-storyboard.md docs/video/ai-digest-closure-style-guide.md
git diff --cached --check
git commit -m "docs: storyboard AI Digest closure video"
```

### Task 4: Safe capture package

**Files:**
- Create: `docs/video/ai-digest-closure-assets.md`
- Create locally, do not commit by default: `.video-work/ai-digest-closure/assets/`
- Read: `docs/video/ai-digest-closure-storyboard.md`

**Interfaces:**
- Consumes: exact asset requests from the storyboard.
- Produces: approved 1920×1080-compatible screenshots/recordings with an asset manifest containing filename, source, crop, duration, and sensitive-data review status.

- [ ] **Step 1: Create an isolated local asset directory**

Resolve and confirm the target is exactly below the repository as `.video-work/ai-digest-closure/assets/`. Add `.video-work/` to `.gitignore` before captures are created so rendered media cannot be added accidentally.

- [ ] **Step 2: Capture product evidence**

Capture the public homepage, one safe detail page for each supported source, search/filter behavior, and a short end-to-end flow representation. Use only public demo data already intended for Pages display.

- [ ] **Step 3: Create evidence graphics**

Prepare transparent or full-frame cards for classifier metrics, test/build results, source architecture, caption-first YouTube logic, and GitHub Pages deployment. Every number must match Task 1.

- [ ] **Step 4: Inspect every asset at full resolution**

Expected: no credential, browser profile, unrelated tab, notification, private path, personal account detail, unreadable crop, or incorrect number is visible. Record `approved` or `rejected` for each asset in `docs/video/ai-digest-closure-assets.md`.

- [ ] **Step 5: Commit only the manifest and ignore rule**

```powershell
git add -- .gitignore docs/video/ai-digest-closure-assets.md
git diff --cached --check
git commit -m "docs: inventory closure video assets"
```

### Task 5: Hyperframes assembly and first export

**Files:**
- Create locally, do not commit by default: `.video-work/ai-digest-closure/exports/ai-digest-closure-v1.mp4`
- Read: `docs/video/ai-digest-closure-storyboard.md`
- Read: `docs/video/ai-digest-closure-style-guide.md`
- Read: `docs/video/ai-digest-closure-assets.md`

**Interfaces:**
- Consumes: narration, shot list, style guide, and approved assets.
- Produces: an editable Hyperframes project and first 1920×1080 MP4 export.

- [ ] **Step 1: Confirm Hyperframes access without exposing account data**

Open Hyperframes in the user’s existing signed-in browser session. If authentication is required, pause for the user to complete it; do not request or handle passwords, tokens, or cookies.

- [ ] **Step 2: Create the project and global style**

Set 16:9 at 1920×1080, establish the approved background/accent/type/subtitle rules, and create the six top-level sections in storyboard order.

- [ ] **Step 3: Assemble shots in timeline order**

Import only assets marked `approved`, apply the exact on-screen copy and motion instructions, and preserve the recurring shared-pipeline visual across relevant sections.

- [ ] **Step 4: Add Traditional Chinese narration and subtitles**

Use the approved narration verbatim except for explicitly recorded pronunciation fixes. Align subtitles to speech, keep lines short enough for 1080p readability, and keep background music below narration.

- [ ] **Step 5: Export version 1**

Export `.video-work/ai-digest-closure/exports/ai-digest-closure-v1.mp4` as 1920×1080 MP4. Record actual runtime and export settings in the asset manifest.

### Task 6: Final audiovisual acceptance and project records

**Files:**
- Create locally, do not commit by default: `.video-work/ai-digest-closure/exports/ai-digest-closure-final.mp4`
- Modify: `docs/video/ai-digest-closure-assets.md`
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: first export and all production documents.
- Produces: final accepted MP4, QA record, and synchronized project progress.

- [ ] **Step 1: Review the first export end to end**

Check runtime, narrative order, subtitle spelling/timing, metric accuracy, text contrast, mobile-size legibility at 1080p, narration/music balance, transition pacing, visible cursor or notification mistakes, and sensitive information.

- [ ] **Step 2: Correct every acceptance finding in Hyperframes**

Do not accept a finding by documenting it. Update the project, re-export, and repeat the complete review until there are no unresolved content, privacy, readability, timing, or audio findings.

- [ ] **Step 3: Export and inspect the final file**

Expected: H.264-compatible MP4, 1920×1080, 5–7 minutes, audible Traditional Chinese narration, synchronized Traditional Chinese subtitles, accurate evidence, and no sensitive content.

- [ ] **Step 4: Record completion truthfully**

Update `docs/video/ai-digest-closure-assets.md` with final filename, runtime, resolution, review date, and result. Update `progress.md` and check a new `todo.md` item only after all final acceptance gates pass.

- [ ] **Step 5: Commit documentation only**

```powershell
git add -- docs/video/ai-digest-closure-assets.md progress.md todo.md
git diff --cached --check
git commit -m "docs: record closure video acceptance"
```

- [ ] **Step 6: Present the final local MP4 to the user**

Provide the exact local path and note that the rendered MP4 has not been committed, pushed, uploaded, or publicly shared unless the user separately authorizes that action.
