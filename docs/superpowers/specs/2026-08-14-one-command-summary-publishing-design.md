# One-Command Summary Publishing Design

## Goal and interface

Provide one Python entry point that turns a directly readable public article into
a validated, committed, deployed, and publicly verified summary:

```powershell
python scripts/publish_url.py 'https://公開文章網址'
```

The script remains within the approved public-web milestone. It does not add
YouTube, social, PDF, OCR, authentication, or a persistent backend.

## Architecture

`scripts/publish_url.py` is an orchestration boundary. It uses existing AI Digest
Python components for URL normalization, repository lookup, and article creation.
It invokes Git, pytest, npm, the deployment verifier, and public HTTP checks through
small injected command/API interfaces so automated tests can replace all external
effects.

This is preferred over parsing all existing CLI text output, which is brittle, or
introducing a general deployment service layer, which is unnecessary for the MVP.

## Workflow

1. Require execution from the repository root on branch `master`.
2. Fetch `origin/master`; stop if local `master` is behind or has diverged.
3. Stop if any tracked file is modified or staged. Preserve and ignore unrelated
   untracked files.
4. Normalize the supplied public HTTP(S) URL.
5. If no saved record has that canonical URL, run the existing add workflow and
   retain the resulting JSON path and ID.
6. If a record already exists, treat it as resumable state and continue only when
   its JSON has not already been published by the current `master` history.
7. Run the full Python suite, frontend tests, Pages production build, and combined
   tracked/dist deployment verification.
8. Stage exactly the one summary JSON. Inspect the staged file list and stop unless
   it contains only that path.
9. Commit with `content: publish <summary-id>` and push `master` to `origin`.
10. Poll GitHub's public Actions API for the pushed commit with a bounded interval
    and total timeout. Require the Pages workflow conclusion to be `success`.
11. Request the public homepage with a cache-busting query and require the summary
    ID to appear. Request the URL-encoded detail route and require HTTP 200.

## Retry behavior

Failures never delete or reset local content. If summary creation succeeds but a
later gate fails, the JSON remains uncommitted. Re-running the same URL discovers
the canonical URL and resumes validation and publication rather than calling the
provider again.

If push succeeds but deployment fails or times out, re-running discovers that the
summary JSON is already in `master`; it does not create an empty commit. It queries
the existing commit's workflow and repeats public verification when appropriate.

## Safety and errors

- API credentials are read only from the existing provider environment variables
  and are never printed, written to JSON, or passed to frontend commands.
- The script never stages with `git add .` and never commits unrelated files.
- A dirty tracked worktree, staged changes, wrong branch, wrong directory, missing
  provider key, remote divergence, invalid URL, failed gate, failed push, failed
  workflow, or failed public check produces a non-zero exit with a concise stage
  and message.
- The script does not merge, reset, delete, force-push, approve npm install scripts,
  or bypass source access controls.
- Untracked files are neither staged nor removed.

## Testing and acceptance

Implementation follows TDD. Tests cover clean and dirty Git state, remote
divergence, new creation, retained-JSON resume, already-pushed resume, exact staging,
gate failure, push failure, workflow success/failure/timeout, URL encoding, and
homepage/detail verification. Git, npm, provider calls, GitHub API, and public HTTP
are replaced in automated tests.

Completion requires the focused tests, full Python suite, frontend tests,
`build:pages`, combined deployment verifier, `git diff --check`, and one user-approved
end-to-end acceptance before documenting the command as ready.

