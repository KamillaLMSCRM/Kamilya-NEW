# YouTube transcript slice — implementation record

**Date:** 2026-08-29
**Status:** locally implemented and validated; feature flag remains off by
default; no production deployment or live YouTube request was performed.

**Scope:** implementation record for the backend worker, ordinary-document
persistence, existing indexing handoff, document-library UI, dependency lock,
and deterministic tests under `apps/api/app/modules/youtube_transcript/`.

## Completed vertical slice

1. `POST /api/v1/youtube/import` validates one allowlisted HTTPS YouTube URL,
   creates a tenant-scoped durable `AIJob`, commits it, and dispatches a
   bounded Celery task.
2. The worker calls `youtube-transcript-api` outside the API event loop with a
   hard timeout and maps provider failures to stable retryable or terminal
   codes. It never downloads media and does not bypass access controls.
3. Normalized subtitles are stored as an ordinary Markdown `Document` in the
   existing object storage and then use the existing `documents.reindex` task.
4. The active-document `(tenant_id, content_sha256)` unique index provides the
   database idempotency backstop; identical imports reuse the existing
   document without a second blob or indexing dispatch.
5. `GET /api/v1/youtube/imports/{job_id}` provides tenant-scoped polling. The
   document library shows the flow only when `YOUTUBE_IMPORT_ENABLED=true`.
6. Local evidence: 35 backend unit/API tests, 10 focused frontend tests,
   clean TypeScript, valid Poetry lock, and one rollback-isolated PostgreSQL 18
   integration test for persistence, RLS context, deduplication, and dispatch.

## What is already implemented (this worktree)

1. `apps/api/app/modules/youtube_transcript/url_resolver.py` — https-only
   allowlist (`youtube.com`, `www.youtube.com`, `m.youtube.com`,
   `music.youtube.com`, `youtu.be`, `www.youtu.be`), canonical 11-char video-id
   extraction (watch / youtu.be / shorts / embed / live), SSRF guards
   (localhost, `.local`, IP literals incl. metadata endpoints, credentials in
   URL), playlist rejection. Stable error codes with Russian UI messages.
2. `apps/api/app/modules/youtube_transcript/provider.py` — provider-neutral
   `TranscriptProvider` protocol, `TranscriptResult`/`TranscriptSegment`
   (provenance: url, video id, title, channel, language, auto-generated flag,
   retrieval time, content hash), retryable-vs-terminal error catalog
   (`provider_blocked`, `provider_timeout`, `provider_unavailable` retryable;
   `transcript_unavailable`, `language_unavailable`, `video_unavailable`,
   `video_too_long`, `transcript_too_short`, `transcript_too_large`
   terminal), MVP limits (120 min, 500k chars, 50k segments, 200-char floor,
   ru/kk/en).
3. `apps/api/app/modules/youtube_transcript/normalizer.py` — validation,
   deterministic plain-text projection with `[mm:ss]` markers, strict
   `document:<sha256>` source revision compatible with the existing ingestion
   contract, provenance dict.
4. `apps/api/app/modules/youtube_transcript/router.py` — tenant-isolated
   router (`require_tenant_user`), `POST /api/v1/youtube/import` (URL
   validation before any provider contact) and `GET /api/v1/youtube/limits`;
   injectable `YouTubeImportService`; without the real adapter the endpoint
   returns structured 503 `provider_unavailable` (retryable) instead of
   pretending success.
5. `apps/api/app/core/config.py` — `YOUTUBE_IMPORT_ENABLED=False` (feature
   flag), `YOUTUBE_MAX_VIDEO_DURATION_SECONDS`, `YOUTUBE_MAX_TOTAL_CHARS`.
6. `apps/api/app/main.py` — router registration.
7. Tests: `apps/api/tests/unit/test_youtube_transcript.py` (24) and
   `apps/api/tests/unit/test_youtube_transcript_api.py` (3). All mocked, no
   live YouTube calls.

## Dependency-policy decision

Neither `youtube-transcript-api` nor `yt-dlp` is present in
`apps/api/pyproject.toml`, `apps/api/requirements.txt`, or
`.codex/tooling/requirements.txt`. Per repository policy the slice adds no new
dependency; the adapter seam (`TranscriptProvider`) is the only integration
point. Plan stages YTG-02 (technical spike) and YTG-06 (experimental adapter
behind the feature flag) must complete before any library is added.

## Remaining steps

### YTG-05 — Upload fallback (SRT/VTT/TXT)

1. Extend `POST /api/v1/youtube/import` (or a sibling `/upload` route) to
   accept SRT/VTT/TXT files when captions are unavailable.
2. Parse into `TranscriptSegment` list; reuse `normalize_transcript` unchanged.
3. Tests: real-file fixtures (small SRT/VTT/TXT), malformed-file terminal
   errors.

### YTG-06 — Experimental captions adapter

1. Complete YTG-02 spike on a public-safe video set (no tenant data).
2. If a library is approved: add it to `pyproject.toml` + `requirements.txt`
   together (Render installs requirements.txt; see 2026-08-24 xlrd
   recurrence), pin the version, keep the adapter isolated — no tenant DB
   credentials, storage credentials, or app secrets inside it.
3. Implement `PublicTranscriptProvider(TranscriptProvider)`; map library
   exceptions to the existing error codes (`provider_blocked` for
   `RequestBlocked`/`IpBlocked`/403/429, `provider_timeout`, `video_unavailable`,
   `transcript_unavailable`, `language_unavailable`).
4. Gate the import endpoint on `YOUTUBE_IMPORT_ENABLED` returning True plus a
   non-stub provider in DI; keep flag off by default in all environments.

## YTG-06 spike results (2026-08-29, documentation-only, no live calls)

Evidence: PyPI JSON API for both packages, official READMEs (raw GitHub),
wheel-level inspection of the downloaded `youtube-transcript-api` wheel
(metadata + `_errors.py` taxonomy). No video, transcript, cookie, or
credential access.

| Criterion | youtube-transcript-api 1.2.4 | yt-dlp 2026.8.19 |
|---|---|---|
| License | MIT (METADATA + classifier) | Unlicense (SPDX `license_expression`) |
| Python | `>=3.8,<3.15` (repo: 3.12 → OK) | `>=3.10` (OK) |
| Runtime deps | `requests`, `defusedxml>=0.7.1,<0.8` only | extras-gated: brotli, certifi, mutagen, pycryptodomex, requests, urllib3, websockets, `yt-dlp-ejs==0.8.0` |
| Wheel | `py3-none-any`, not yanked, 2026-01-29 | `py3-none-any`, not yanked, 2026-08-19 |
| Maintenance | active single maintainer + contributors, CI/coverage badges | very active, calendar-versioned |
| Transcript coverage | captions only (manual + auto), language filter, `is_generated` flag | captions among many other functions (media downloader focus) |
| Auto captions | yes, `is_generated` flag distinguishes | yes |
| Proxy/rate-limit risk | documented cloud-IP blocking (`RequestBlocked`/`IpBlocked`); proxy config optional; no proxy added in this slice | same YouTube blocking, plus larger extractor surface |
| Supply-chain surface | small: 2 runtime deps, ~15 modules | large: extractor zoo, default extras, `yt-dlp-ejs` pin |
| Failure taxonomy | rich typed exceptions incl. `TranscriptsDisabled`, `NoTranscriptFound`, `VideoUnavailable`, `RequestBlocked`, `IpBlocked`, `AgeRestricted` | exceptions exist but coupled to downloader flow |

**Decision:** `youtube-transcript-api` selected as the experimental public
caption adapter. yt-dlp rejected for this slice: Unlicense license (weaker
match for the repository's MIT-family posture), no hard dependency boundary,
media-downloader orientation, and a materially larger supply-chain surface.

**Installed as (both files updated in one commit per xlrd recurrence):**
- `apps/api/pyproject.toml`: `youtube-transcript-api = ">=1.2.4,<2.0.0"`
- `apps/api/requirements.txt`: `youtube-transcript-api>=1.2.4,<2.0.0`

**Implemented:** `public_caption_adapter.py` with lazy import, exception
mapping (`RequestBlocked`/`IpBlocked` → retryable `provider_blocked`;
`TranscriptsDisabled`/`NoTranscriptFound` → terminal `transcript_unavailable`;
`VideoUnavailable` → terminal `video_unavailable`; `YouTubeRequestFailed` →
retryable `provider_unavailable`), normalization to `TranscriptResult` with
provenance, DI via `build_router_service()` which returns the adapter only
when `YOUTUBE_IMPORT_ENABLED=True` and otherwise keeps the structured 503
`provider_unavailable` fallback. Tests fake the library module; no network.

### YTG-07 — Document integration (persistence)

1. Persist a `Document` row from `NormalizedTranscriptSource` through the
   existing upload path: tenant-scoped, `uploaded_by`, `content_type`
   `text/markdown`, `content_sha256` precomputed, `source_revision` passed to
   `DocumentIngestion.ingest_file` (it already validates the strict
   `document:<64 hex>` form).
2. Idempotency: lookup by `(tenant_id, content_sha256)` active-document unique
   index (`uq_documents_active_tenant_content_sha256`) before insert; reuse on
   match and return `idempotent_reuse: true`. IntegrityError on the same index
   maps to reuse (pattern: `_is_active_document_hash_unique_violation`).
3. Tenant isolation: RLS with `set_current_tenant` in the same transaction as
   the insert; cross-tenant negative test required.
4. Enqueue indexing through the existing AI-job path; no parallel pipeline.

### API/UI states (Russian) — wire-through

- `transcript_unavailable` → offer SRT/VTT/TXT upload.
- `language_unavailable` → show detected languages, request choice.
- `provider_blocked`/`provider_timeout`/`provider_unavailable` → temporary
  unavailability, no infinite retry.
- `video_too_long`, `transcript_too_short`, `transcript_too_large` → no
  generation start.
- Auto captions → persistent review warning before publish.

## Explicit non-goals (unchanged)

No video/audio download, no access-control circumvention, no proxy/blocks
bypass, no production deployment, no new third-party dependency in this slice.
