# Failed-image fallback design

**Date:** 2026-08-29  
**Status:** Approved approach; awaiting written-spec review

## Problem

The homepage currently hides an OG image only after an `error` event or when the image is already `complete` with `naturalWidth === 0`. When Chrome blocks images for the public Pages site, each image remains `complete=false`, `naturalWidth=0`, and `hidden=false`; no `error` event is delivered. The browser therefore renders a broken-image icon and alt text above the source fallback.

## Scope

This change only affects homepage OG-image presentation. It does not change summary data, schemas, URLs, image generation, detail pages, source parsing, or the approved responsive layout.

## Design

Each `.summary-card-image` uses an explicit client-side presentation state:

- `pending`: applied during initialization before relying on browser completion events. The image is visually hidden and the existing source fallback remains visible.
- `loaded`: applied after a successful `load`, or immediately when a cached image is already complete with `naturalWidth > 0`. The image is visible above the fallback.
- `failed`: applied after `error`, or immediately when a completed image has `naturalWidth === 0`. The image remains visually hidden and the fallback remains visible.

Images that remain indefinitely incomplete because of browser content blocking stay `pending`; this is intentional fail-closed behavior. Lazy loading remains enabled. The existing image `alt` text remains unchanged for accessibility when the image successfully loads.

The state is represented by a `data-image-state` attribute on the image. CSS hides `pending` and `failed` images and shows only `loaded` images. The frame and fallback keep their existing dimensions, colors, source label, and responsive placement.

## Error handling

Image loading must never remove a card or prevent filtering, sorting, searching, or navigation. An image without a confirmed successful load displays the source fallback. A later successful `load` may transition `pending` to `loaded`; an `error` transitions any state to `failed`.

## Tests and acceptance

TDD coverage must first fail against the current implementation and then cover:

1. initial `pending` state before an image is confirmed loaded;
2. successful `load` transition to `loaded`;
3. cached successful image initialization as `loaded`;
4. `error` transition to `failed`;
5. cached completed failure initialization as `failed`;
6. CSS visibility rules that expose only `loaded` images;
7. preservation of `loading="lazy"`, `object-fit: contain`, source fallback markup, and responsive layout.

Verification requires the focused Vitest tests, the complete Vitest suite, `npm run build:pages`, deployment verification, and `git diff --check`. After deployment, Chrome must block images for the public Pages site and visually confirm that source fallback text replaces broken-image UI without horizontal overflow; image permission must then be restored.

## Non-goals

- Retrying or polling blocked images.
- Adding a backend or service worker.
- Changing image URLs or OG generation.
- Suppressing genuine images globally.
- Expanding the homepage feature set.
