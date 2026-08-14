# Git Path Deployment Verifier Design

## Problem

The deployment verifier reads `git ls-files` as locale-decoded, line-delimited
text. Git quotes non-ASCII paths by default, so the tracked Chinese summary file
is returned as a quoted octal escape sequence. The verifier treats that display
form as a real path and fails before the Astro build. On Windows, a Git error that
contains a UTF-8 repository path can also be masked by a CP950 decode failure.

Workflow run `31766478611` therefore stopped at
`python scripts/verify_deployment.py --tracked`; build and deploy were skipped.

## Decision

Read tracked paths with `git ls-files -z` in binary mode. Split stdout on NUL
bytes and decode each path with UTF-8 plus `surrogateescape`, which preserves any
unexpected path bytes without Git display quoting or locale-dependent decoding.

Keep the existing `--tracked`, `--dist`, and `--base` interfaces and all sensitive
data checks unchanged. A non-zero Git exit remains fatal and must expose a safe,
readable error rather than continuing with an incomplete file set.

## Testing

TDD coverage will mock a NUL-delimited Git result containing a Chinese filename,
create that file in a temporary repository directory, and assert that `main()`
scans it successfully. A second test will confirm Git failures remain failures
without locale decoding exceptions.

Verification requires the focused verifier tests, full Python suite,
`git diff --check`, the real deployment verifier against tracked files and
`site/dist`, a push to `master`, a successful GitHub Pages workflow for the new
commit, and public confirmation that the new summary ID appears.

