# Gemini Default Model Migration Design

## Problem

The configured default `gemini-2.5-flash` is discoverable through `models.list`
but rejects generation for this new API user with HTTP 404 and an instruction to
use a newer model. This blocks the approved live acceptance after extraction.

## Decision

Change the Gemini default model to the stable, versioned
`gemini-3.6-flash`. Google documents this model as generally available and as
supporting structured outputs. A fixed stable model is preferred over
`gemini-flash-latest`, whose backing version can change without a repository
change.

The `GEMINI_MODEL` environment override remains unchanged. There is no automatic
fallback, provider switch, prompt change, Schema change, or migration to the
Interactions API in this work unit.

## Changes

- Update the CLI's default Gemini model string.
- Update automated CLI expectations for the default while retaining explicit
  override coverage.
- Update README configuration examples and project progress records.
- Complete one isolated live acceptance with the approved article URL.

## Testing and acceptance

TDD begins with a CLI test expecting `gemini-3.6-flash`; it must fail against the
old default before production code changes. The focused CLI tests and full Python
suite must pass afterward.

Live acceptance must use the default model, write to a unique temporary directory,
complete all pipeline stages, and produce exactly one Schema-valid JSON record.
The record must contain no credential names or values. The live result and any
remaining risks are recorded in `progress.md` and `todo.md`.

