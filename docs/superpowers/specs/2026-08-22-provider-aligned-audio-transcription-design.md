# Provider-aligned audio transcription design

Date: 2026-08-22
Status: Approved

> Superseded in part on 2026-08-25: Gemini Files deletion now uses the bounded retry and HTTP 404 semantics defined in `2026-08-25-gemini-file-cleanup-retry-design.md`. All other provider-aligned transcription requirements remain in force.

## 1. Goal and scope

AI Digest will keep both Gemini and OpenAI providers. The existing `AI_DIGEST_PROVIDER` setting will select one provider for the complete `add` workflow: both structured summarization and the audio transcription fallback for public YouTube videos without usable captions.

The approved behavior is:

- `AI_DIGEST_PROVIDER=gemini` uses only `GEMINI_API_KEY`, `GeminiSummarizer`, and `GeminiAudioTranscriber`.
- `AI_DIGEST_PROVIDER=openai` uses only `OPENAI_API_KEY`, `OpenAISummarizer`, and `OpenAIAudioTranscriber`.
- There is no automatic cross-provider fallback.
- Captioned YouTube videos continue to use captions and never download or transcribe audio.
- The public-source, duration, access-control, storage, and frontend scope from the approved YouTube design remains unchanged.

This change does not add another provider, a provider-specific CLI command, saved transcripts, a backend service, or credential persistence.

## 2. Approved approach

Use one provider selection for the complete AI workflow. This keeps configuration predictable, prevents a Gemini workflow from unexpectedly requiring an OpenAI key, and preserves the existing no-fallback policy.

Rejected alternatives:

- A separate transcription-provider setting would add configuration and a larger test matrix without serving the current MVP.
- Automatic fallback would create unexpected cost and credential requirements and would conflict with the existing provider contract.

## 3. Architecture and responsibilities

The existing `AudioTranscriber` protocol remains the boundary consumed by `YouTubeExtractor`. The extractor remains provider-agnostic and continues to own only captions-first orchestration:

```text
AI_DIGEST_PROVIDER
  |-- gemini
  |     |-- GeminiSummarizer
  |     `-- GeminiAudioTranscriber
  `-- openai
        |-- OpenAISummarizer
        `-- OpenAIAudioTranscriber

YouTubeExtractor
  |-- usable captions -> extracted text
  `-- no captions
        -> YouTubeMediaPipeline
        -> selected AudioTranscriber
        -> extracted text
```

Create `src/ai_digest/transcribers/gemini.py` for the Gemini SDK adapter. It must not fetch YouTube content, summarize, classify, or save records. Existing OpenAI modules remain supported.

CLI composition selects the summarizer and lazy transcriber factory from the same normalized `AI_DIGEST_PROVIDER` value. The selected provider key is validated before audio download when a no-caption route actually needs transcription. Ordinary local commands remain key-free.

## 4. Gemini transcription lifecycle

For each FFmpeg-produced MP3 chunk, in source order:

1. Upload the chunk with the Gemini Files API.
2. Ask the selected Gemini transcription model to return a faithful transcript only, without summarizing, translating, inventing, or adding commentary.
3. Validate that the response contains non-blank text.
4. Delete the uploaded Gemini file in a `finally` cleanup path.
5. Append the validated text only after the chunk has completed successfully.

After every chunk succeeds, join transcripts in their original order. If any upload, generation, response validation, or remote cleanup operation fails, the transcriber raises a safe error and does not return a partial transcript.

Gemini supports MP3 audio input. The Files API is used for every chunk rather than mixing inline and uploaded modes; this gives one lifecycle and supports chunks beyond the inline request limit. The existing local chunk-duration and maximum-byte protections remain in force.

Remote Gemini files, local audio chunks, source captions, and complete transcripts must never be written to summary JSON, frontend assets, logs, fixtures containing real data, or tracked files.

## 5. Configuration

Provider selection remains:

```dotenv
AI_DIGEST_PROVIDER=gemini
```

Provider-specific models are explicit:

```dotenv
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TRANSCRIPTION_MODEL=gemini-3.6-flash
OPENAI_MODEL=gpt-5-mini
OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe
```

`AI_DIGEST_TRANSCRIPTION_MODEL` is replaced by the provider-specific variables so switching providers cannot accidentally send an incompatible model ID. The existing shared settings remain:

```dotenv
AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS=600
AI_DIGEST_TRANSCRIPTION_MAX_CHUNK_BYTES=25165824
AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS=7200
```

Only the selected provider key is required. Keys remain local environment values and are never written to repository files or output.

## 6. Error handling and safety

The public error contract remains `DigestError(stage, code, message, retryable)`. Gemini transcription maps failures to the existing extract-stage codes:

| Condition | Code | Retryable |
|---|---|---:|
| Request timeout | `TRANSCRIPTION_TIMEOUT` | `true` |
| Rate limit | `TRANSCRIPTION_RATE_LIMITED` | `true` |
| Transport or server failure | `TRANSCRIPTION_FAILED` | `true` |
| Client rejection, invalid response, local read failure, or cleanup failure | `TRANSCRIPTION_FAILED` | `false` |

Process-control exceptions must still propagate after cleanup. Public exceptions must not expose API keys, complete source URLs, transcript content, local paths, Gemini file names or URIs, prompts, or raw SDK responses.

The adapter must attempt deletion for every successfully uploaded Gemini file. Cleanup failure is a transcription failure because the remote temporary resource lifecycle is part of the security contract. If transcription and cleanup both fail, preserve the primary safe failure while suppressing sensitive cleanup details.

## 7. TDD and verification

Implementation follows strict red-green-refactor sequencing.

Add focused Gemini transcriber tests using fake clients for:

- ordered upload, transcription, cleanup, and transcript merging;
- cleanup after success, failure, and interruption;
- blank and malformed responses;
- timeout, rate limit, client, server, transport, and unexpected SDK failures;
- no partial transcript after any chunk failure;
- no secret, file URI, transcript, or path leakage.

Update CLI tests to prove:

- Gemini selects both Gemini adapters and requires only `GEMINI_API_KEY`;
- OpenAI selects both OpenAI adapters and requires only `OPENAI_API_KEY`;
- neither path silently falls back;
- missing selected-provider credentials fail before audio download;
- provider-specific transcription model defaults and overrides are wired correctly.

Retain and rerun all OpenAI transcriber tests. Complete verification includes the full Python suite, frontend tests, Astro production build, schema and saved-data validation, `git diff --check`, and sensitive-data/media scans.

## 8. Manual acceptance

After automated verification succeeds, run an isolated live acceptance against the user-approved public no-caption video:

`https://www.youtube.com/watch?v=4gciWspBVHw`

Use `AI_DIGEST_PROVIDER=gemini`. Verify that the workflow downloads and cleans local audio, uploads and deletes Gemini files, produces a non-empty transcript internally, creates a valid `sourceType: youtube` and `status: published` record, and stores no transcript artifact or local/remote file reference.

Only after this succeeds may the YouTube real-case acceptance item be marked complete in `todo.md`. Record actual verification results, external limitations, risks, and the next step in `progress.md`. Do not publish, push, or deploy as part of this acceptance.

## 9. Documentation updates

Update the approved YouTube design to note that its original OpenAI-only transcription choice is superseded by this provider-aligned design. Update `.env.example` and `README.md` to describe the two provider-specific transcription models and single-provider behavior. Remove statements implying that Gemini YouTube ingestion requires an OpenAI key.

## 10. References

- `docs/superpowers/specs/2026-08-09-ai-digest-mvp-design.md`
- `docs/superpowers/specs/2026-08-21-youtube-source-design.md`
- Gemini audio understanding: <https://ai.google.dev/gemini-api/docs/audio>
- Google Gen AI Python SDK: <https://googleapis.github.io/python-genai/>
