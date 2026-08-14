# Gemini Default Model Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unavailable Gemini default with stable `gemini-3.6-flash` and complete the approved live acceptance.

**Architecture:** Keep provider composition and environment overrides unchanged. Update only the default model constant expressed in CLI composition, its tests, and user-facing configuration documentation.

**Tech Stack:** Python 3.12+, pytest, google-genai, Markdown

## Global Constraints

- Default to the fixed stable model `gemini-3.6-flash`; do not use a moving alias.
- Preserve `GEMINI_MODEL`, OpenAI behavior, provider selection, prompts, Schema, and error structures.
- Use TDD and observe the changed default expectation fail before editing production code.
- Make exactly one additional full live acceptance attempt after automated verification.

---

### Task 1: Migrate the tested default model

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/ai_digest/cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `_summarizer() -> Summarizer` and `GEMINI_MODEL`.
- Produces: default `GeminiSummarizer` model `gemini-3.6-flash`; explicit overrides remain exact.

- [ ] **Step 1: Change the default-model test expectation to `gemini-3.6-flash`.**
- [ ] **Step 2: Run the focused CLI test and confirm it fails with actual `gemini-2.5-flash`.**
- [ ] **Step 3: Change only the CLI default string to `gemini-3.6-flash`; update both README occurrences.**
- [ ] **Step 4: Run all CLI tests, then the complete Python suite and `git diff --check`.**
- [ ] **Step 5: Commit tests, implementation, and README as `fix: update default Gemini model`.**

### Task 2: Repeat live acceptance and record evidence

**Files:**
- Modify: `progress.md`
- Modify: `todo.md`

**Interfaces:**
- Consumes: the default Gemini model through `.venv\Scripts\ai-digest.exe add`.
- Produces: one temporary Schema-valid summary record and updated project status.

- [ ] **Step 1: Run one `add` for `https://pala.tw/python-web-crawler/` with no `GEMINI_MODEL` override and a unique temporary summary root.**
- [ ] **Step 2: Load the JSON with `SummaryRepository`; verify canonical URL, published status, 3–5 key points, valid category, non-empty tags, and absence of credential material.**
- [ ] **Step 3: Record redirect fix, model migration, live result, model name, record ID, and verification evidence in `progress.md`; check only the completed Gemini live acceptance item in `todo.md`.**
- [ ] **Step 4: Run the full Python suite, `git diff --check`, and `git status --short`.**
- [ ] **Step 5: Commit `progress.md` and `todo.md` as `docs: record Gemini live acceptance`.**

