# Redirect Trailing-Slash Handling Design

## Problem

`normalize_public_url()` removes a non-root trailing slash. `WebExtractor` currently
uses that canonical form both as the saved URL and as the HTTP transport URL for
every redirect hop. A server that redirects `/article` to `/article/` therefore
causes a loop: redirect validation normalizes `/article/` back to `/article` before
the next request.

The approved acceptance URL, `https://pala.tw/python-web-crawler/`, exposes this
behavior and fails with `TOO_MANY_REDIRECTS` before Gemini is called.

## Scope and chosen approach

Keep canonicalization and transport concerns separate inside the existing web
extractor:

- Continue using `normalize_public_url()` for the canonical URL stored in an
  `ExtractedArticle`.
- Preserve the server-provided trailing slash in the transport URL used for the
  next HTTP request.
- Continue validating every redirect destination through the existing DNS and
  public-address checks before connecting.
- Keep the redirect limit, pinned address, `Host` header, SNI behavior, error
  structure, Schema, and CLI interface unchanged.

This is preferred over retaining trailing slashes globally (which would change
canonical URL and duplicate-detection behavior) or special-casing WordPress (which
would be platform-specific and incomplete).

## Data flow

For each input or redirect destination, validation produces two values:

1. A normalized canonical URL for identity and eventual storage.
2. A safe transport URL that retains the destination path's trailing slash while
   using the validated, pinned public IP for the actual connection.

Relative redirects are resolved against the current transport URL. Successful
extraction returns the normalized canonical URL corresponding to the final safe
destination.

## Error and security behavior

No access restriction is relaxed. Each hop must still be HTTP(S), resolve only to
global addresses, and pass the existing response limits. Redirect loops unrelated
to canonical trailing-slash removal still end with `TOO_MANY_REDIRECTS`.

## Tests and acceptance

TDD coverage will first reproduce a server redirect from `/article` to `/article/`
and assert that the second request retains the slash and extraction completes. The
existing redirect-limit and private-destination tests must remain green.

Verification consists of:

1. The focused extractor test.
2. The complete Python test suite.
3. `git diff --check`.
4. One live `ai-digest add` using the approved URL, Gemini, and an isolated
   temporary summary directory.
5. Validation and inspection of the resulting JSON without exposing credentials.

