# Task 6 report: classifier review batch one

## Delivered data

- Added `data/classifier/training.csv` with 60 batch-one candidates, all marked `pending`.
- The six configured categories each contain 10 rows: `人工智慧`, `程式開發`, `科技產業`, `商業與職場`, `設計與創意`, and `生活與學習`.
- Added the reviewer guide with the allowed review-field edits, replacement-row procedure, and offline `load_dataset` count commands that work with active/on-PATH `python` or, optionally, the main checkout interpreter from this worktree.

## Research method and limits

Research was completed on 2026-08-19 by opening each candidate HTTP(S) page individually and confirming direct public readability, article title, and enough body content to determine its dominant subject. Login/paywall/anti-bot pages, list pages, duplicate canonical URLs, ambiguous candidates, and pages that returned internal errors were excluded. Dataset text is a Traditional Chinese paraphrase; no cookies, tokens, page dumps, or substantial quotations were retained.

Publisher concentration remains a known residual concern: the artificial-intelligence and life-and-learning categories have relatively concentrated publishers. Batch two and three should diversify publishers, and classifier preparation should inspect for publisher-vocabulary shortcut learning. The technology category was corrected to use Apple, NVIDIA, and Google sources.

## Validation

- Offline `load_dataset` validation: 60 rows; every row is batch 1 and `pending`; each category has 10 rows.
- Tracked-file sensitive-data scan: `python scripts/verify_deployment.py --tracked --base /AI-Summary/` exited 0. No `--dist` check was run because this task does not modify frontend output and `site/dist` is absent.
- `git diff --check` exited 0.

## Files and commit

- `data/classifier/training.csv`
- `docs/classifier-review.md`
- `progress.md`
- `todo.md`
- `.superpowers/sdd/task-6-report.md`

Commit: `data: add classifier review batch one`
