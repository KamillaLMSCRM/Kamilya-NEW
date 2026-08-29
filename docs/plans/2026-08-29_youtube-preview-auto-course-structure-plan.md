# YouTube preview and automatic course structure plan

Date: 2026-08-29
Owner: root orchestrator
Status: implementation in isolated agent worktrees
Production mutation: not authorized

## Product outcome

Replace the technical `URL -> document` interaction with one coherent flow:

`source -> analysis -> concise preview -> recommended course format -> methodologist confirmation -> document/index reuse -> course generation -> draft review`.

The same course-format contract must work for one document, multiple documents,
and a YouTube transcript. A normal HR employee should not need to choose an
abstract module count.

## Decisions

1. YouTube analysis is provisional. It must not create a permanent `Document`
   before the methodologist confirms an action.
2. Preview returns a factual one- or two-sentence summary, detected language,
   manual/automatic caption status, duration, quality state, key topics, and a
   recommended course format.
3. Primary confirmation is `Create course from video`; secondary confirmation
   is `Save captions to documents`.
4. Confirmation is idempotent and single-consumption safe. Raw transcript is
   stored in a tenant-scoped temporary object, not in `AIJob.result`.
5. Temporary analysis sessions expire and are cleaned up. No raw transcript,
   URL query payload, PII, or credentials may be logged.
6. The ordinary `Document`, object storage, indexing, AI job, and course
   generation pipelines remain authoritative. No second RAG pipeline.
7. The primary generation UI replaces raw module count with course format:
   `automatic`, `brief`, `standard`, or `detailed`.
8. Automatic is the default. Backend source analysis recommends target
   duration, semantic module count, lesson count, and assessment density.
9. Manual module count remains optional under advanced settings and must be
   validated against the source recommendation.
10. The feature remains off by default until a bounded dev live-caption smoke
    is separately authorized and passes.

## Agent workstreams

### A. YouTube provisional analysis backend

Write scope:

- `apps/api/app/modules/youtube_transcript/`
- one additive Alembic migration after current head if required
- focused backend tests for this module
- this plan only for factual implementation notes

Required result:

- tenant-scoped provisional session persistence and RLS;
- temporary source object with expiry;
- async analyze/status/confirm API;
- factual concise preview through an injectable summarization seam;
- confirm-save and confirm-generate orchestration without duplicate documents;
- cleanup task and deterministic tests;
- no production, commit, push, or deployment.

### B. Automatic course-structure backend

Write scope:

- `apps/api/app/modules/ai/source_analysis.py`
- `apps/api/app/modules/ai/schemas.py`
- `apps/api/app/modules/ai/router.py`
- focused AI tests
- this plan only for factual implementation notes

Required result:

- course format enum and recommendation DTO;
- recommendation based on semantic topics, source size, learning goals, and
  target duration rather than page count alone;
- default automatic mode;
- advanced manual module override remains backwards-compatible;
- warning/rejection for unreasonable overrides;
- existing generation consumers remain compatible;
- deterministic unit and integration tests;
- no production, commit, push, or deployment.

### C. Methodologist frontend flow

Write scope:

- `apps/web/src/app/documents/page.tsx`
- `apps/web/src/app/ai/generate/page.tsx`
- `apps/web/src/i18n/locales/{ru,kk,en}.json`
- focused frontend tests
- this plan only for factual implementation notes

Required result:

- `Analyze video` first action;
- concise preview card with source quality and recommendation;
- separate `Create course from video` and `Save captions` actions;
- replace primary module-number field with understandable course formats;
- keep manual module override under advanced settings with explanatory copy;
- preserve forms on backdrop clicks during an active operation;
- accessible loading, failure, expiry, and retry states;
- deterministic frontend tests and clean typecheck;
- no production, commit, push, or deployment.

## Root integration gates

1. Review every agent diff against this plan and existing deep-module seams.
2. Reconcile API contracts before copying frontend code.
3. Preserve unrelated dirty work in the main worktree.
4. Add or adjust migration only after validating the current Alembic head.
5. Run version consistency and update `[Unreleased]` without a version bump.
6. Run backend unit/integration tests against the local PostgreSQL 18 contour.
7. Run focused frontend tests and typecheck from the main pinned dependencies.
8. Perform no live YouTube request, push, deploy, environment change, or
   production mutation without a separate exact approval.

## Acceptance criteria

- No permanent document exists before explicit confirmation.
- Preview summary is no more than two concise factual sentences.
- Auto-caption status and quality warning remain visible before generation.
- One confirmation creates or reuses exactly one document.
- Repeated confirmation does not create a second document or generation job.
- `automatic` course format requires no module-number decision from HR staff.
- Brief, standard, and detailed formats have clear target-duration semantics.
- Manual module override is advanced-only and cannot force an obviously
  unreasonable structure without a clear warning or validation response.
- One-document, multi-document, and YouTube generation use the same backend
  recommendation contract.
- Tenant isolation, RLS, expiry cleanup, idempotency, and no-PII logging have
  proportional automated coverage.
