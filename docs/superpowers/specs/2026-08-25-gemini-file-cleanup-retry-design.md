# Gemini Files cleanup retry design

Date: 2026-08-25
Status: Implemented; live acceptance blocked

## 1. Context and goal

The approved no-caption YouTube acceptance reached Gemini audio transcription twice. The first run produced a valid saved record but exposed a separate Windows CP950 CLI output issue, which is now fixed. The second run stopped safely because the single Gemini Files API delete call failed after transcription. The one uniquely identified remote audio file was subsequently deleted and the Files list was confirmed empty.

This change makes remote cleanup resilient to short-lived Gemini Files API failures without weakening the existing fail-closed behavior. It remains part of the provider-aligned YouTube MVP and does not change source extraction, summarization, classification, storage, or frontend responsibilities.

## 2. Approved approach

Implement bounded cleanup retry inside `GeminiAudioTranscriber`. Only `client.files.delete()` is retried. Upload, generation, response validation, summarization, and OpenAI behavior remain unchanged.

The adapter will make at most three delete attempts:

1. Attempt deletion immediately.
2. After a retryable first failure, wait 1 second and retry.
3. After a retryable second failure, wait 2 seconds and retry once more.

The sleeper is injected into `GeminiAudioTranscriber`, defaulting to `time.sleep`. Tests replace it with a recording fake, so routine tests do not wait or use external services.

Rejected alternatives:

- Gemini SDK global retry configuration is too broad because it can change upload and generation behavior and is more tightly coupled to SDK defaults.
- CLI-level reconciliation by listing account Files risks acting on unrelated files and would add account-wide cleanup behavior outside the adapter boundary.
- Unbounded retries, ignored cleanup failures, background cleanup, and cross-provider fallback are outside the approved scope.

## 3. Error classification

Deletion outcomes are classified as follows:

- Success: deletion returns normally.
- Idempotent success: Gemini returns HTTP 404. The required end state is already true because the uploaded file no longer exists.
- Retryable failure: `httpx.TimeoutException`, `httpx.TransportError`, Gemini `ClientError` with status 429, or Gemini `ServerError` representing a 5xx response.
- Non-retryable failure: any other ordinary exception, including Gemini 4xx responses other than 404 and 429.
- Control-flow interruption: `KeyboardInterrupt` or `SystemExit`; propagate immediately without sleeping or retrying.

After three retryable failures, or after one non-retryable failure, cleanup remains failed. Public errors must not include the Gemini file name or URI, local media path, source URL, transcript, API key, SDK response, or raw exception text.

## 4. Primary-error precedence

The existing precedence rules remain in force:

- If upload fails, no remote cleanup is attempted because no uploaded file was returned.
- If generation or response validation fails, cleanup is still attempted with the bounded retry policy.
- If generation and cleanup both fail, the safe mapped generation error remains primary; cleanup must not replace it.
- If generation succeeds but cleanup ultimately fails, return `DigestError` with stage `extract`, code `TRANSCRIPTION_FAILED`, message `Audio transcription cleanup failed`, and `retryable=false`.
- A transcript is appended only after generation, validation, and cleanup all complete successfully. Partial transcripts are never returned.

## 5. Component boundary

The implementation remains within `src/ai_digest/transcribers/gemini.py`:

- `GeminiAudioTranscriber` receives the Gemini client, model name, and an optional sleeper.
- A focused private cleanup method owns delete classification, bounded attempts, and delays.
- `YouTubeExtractor` continues to consume only the `AudioTranscriber` protocol.
- CLI composition and environment variables do not change.
- `OpenAIAudioTranscriber` does not change.

No new public CLI flags, environment settings, persistent queues, saved transcripts, account-wide Files scans, or background services are introduced.

## 6. Test strategy

Strict TDD will add focused fake-client tests before implementation. The tests will cover:

- deletion succeeding on the first attempt with no sleep;
- a retryable first failure followed by success, with one 1-second sleep;
- two retryable failures followed by success, with sleeps exactly `[1, 2]`;
- three retryable failures producing the existing safe cleanup error;
- HTTP 404 treated as cleanup success without sleep;
- non-retryable 4xx and unexpected exceptions failing immediately without sleep;
- generation error remaining primary when cleanup also exhausts retries;
- `KeyboardInterrupt` and `SystemExit` propagating immediately without retry;
- no file names, URIs, paths, prompts, transcripts, API keys, or raw SDK details in public errors.

All automated tests use fakes and local fixtures. They do not require network access, media binaries, or paid API calls.

## 7. Verification and live acceptance

After focused and complete Python tests pass, run the existing frontend tests, Astro production build, Schema/storage tests, deployment verifier, `git diff --check`, sensitive-data checks, and media-residue scan.

Only after those gates pass, rerun the already approved no-caption public video in a new absent isolation directory with the Gemini provider. The live run must:

- reach the CLI `complete` stage;
- create exactly one JSON record;
- pass `SummaryRecord` validation;
- contain `sourceType=youtube`, the exact canonical URL, `published` status, non-empty summary and editorial, and 3–5 key points;
- contain no local repository path, media extension, Gemini file name, or Gemini URI;
- leave no local media files;
- leave no Gemini File created by the acceptance run.

Delete only the exact isolated acceptance directory after validation. Do not list or delete unrelated account Files. If remote cleanup fails again, stop, preserve safe diagnostic evidence, and do not perform repeated paid acceptance attempts without a new decision.

The overall todo item for one approved captioned and one approved no-caption case remains unchecked until both cases have complete recorded evidence.

## 8. Files and scope

Expected implementation changes are limited to:

- `src/ai_digest/transcribers/gemini.py`;
- `tests/test_gemini_transcriber.py`;
- this design, the supersession note in the 2026-08-22 provider-aligned design, and the implementation plan;
- `progress.md` and `todo.md` for verified evidence.

Any change to public data format, CLI interface, provider selection, retry configuration, or other source parsers requires separate approval.

## 9. Implementation and verification evidence

The approved implementation is present in `GeminiAudioTranscriber`; no parser, summary provider, CLI interface, data format, or OpenAI behavior changed.

| Requirement | Task evidence |
|---|---|
| Delete only, at most three attempts, with delays exactly 1.0 then 2.0 seconds | Task 1 implementation in `src/ai_digest/transcribers/gemini.py`; Task 2 focused fake-client tests assert the delete attempt count and recorded delays. |
| 404 succeeds; timeout, transport, 429, and 5xx retry; other failures stop; interruptions propagate | Task 2 focused Gemini transcriber tests cover each classification and assert no unnecessary sleep or retry. |
| Generation failure remains primary when cleanup also exhausts retries; no partial transcript | Task 2 focused tests cover primary-error precedence and safe failure mapping. |
| Automated tests have no real sleep, network, media-binary, or paid API dependency | Task 2 uses injected sleepers, fake clients, and local fixtures; the 2026-08-25 full local suite passed 452 tests. |

On 2026-08-25, fresh local gates passed: Python `452 passed, 2 warnings`; Schema/storage `28 passed, 1 warning`; Vitest `25 passed`; Astro `0 errors / 0 warnings / 0 hints` and `5` pages; deployment verification and `git diff --check` exited 0; `site/dist` media residue was 0. The required tools were `yt-dlp 2026.08.19` and FFmpeg `9.0.1`; the Gemini key presence check succeeded without exposing its value.

Exactly one approved no-caption live invocation was attempted with `gemini-3.6-flash`. Its acceptance root did not exist afterward and contained `0` JSON records, so the required record validation could not pass. The Gemini Files non-identifying count was `0` before and `0` after the invocation; no remote File metadata was printed or deleted. There was no uniquely identifiable local acceptance record to remove. A fresh paid retry requires a new decision. The combined captioned/no-caption acceptance remains incomplete.
