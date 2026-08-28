# Kamilya Test Run Ledger

This append-only ledger stores sanitized, version-controlled evidence from the
persistent Kamilya Test & Evidence Runner. It is not a replacement for CI,
provider/runtime readback, `ERRORS.md`, critical-journey contracts, or root review.

Rules:

- never edit or delete an accepted run entry; append a correction referencing it;
- never store secrets, `.env` values, PII, tenant payloads, contact data, or raw
  production logs;
- use exact immutable Git SHA and UTC timestamps;
- distinguish product, harness, access, and provider failures;
- historical green results are not evidence for a later SHA or runtime;
- only one active writer owns this file at a time.

## RUN-20260828-HELP-TEAM-MODAL-01

- Timestamp: `2026-08-28T05:30:00Z`
- Executor: root orchestrator (seed entry before Test Runner ownership)
- Exact SHA: `d3d7ec3428a1730a1f68d76d09aea065acea7741`
- Scope: shared modal portal, contextual help viewport containment, create-user
  backdrop preservation
- Local matrix:
  - focused Vitest: `2 files, 18 tests passed`
  - TypeScript: `PASS`
  - Next.js production build: `PASS`, `57/57` static pages
- CI:
  - dev run `33144847798`: `success`
  - master run `33145064607`: `success`
- Provider evidence:
  - Vercel production: `READY`, exact SHA, alias `app.kml.kz`
- Production browser evidence:
  - help dialog parent: `document.body`
  - viewport `1920x911`; dialog `y=47.5`, height `816`, bottom `863.5`
  - create-user backdrop click: dialog remained open
  - `Escape`: dialog closed
- Evidence labels: `GIT-DERIVED`, `PROVIDER-CONFIRMED`, `RUNTIME-DERIVED`
- Result: `PASS_WITH_FOLLOW_UP`
- Follow-up: add a visible explicit close control to the create-user modal; the
  current production form closes by `Escape` but has no visible close button.
- Cleanup: no user created, no mail sent, no production data mutation
- Root review: accepted evidence; UX follow-up remains open
