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

## RUN-20260828-PLUS-FULLFLOW-02

- Timestamp: `2026-08-28T06:30:00Z` (UTC; sanitized runner record)
- Executor: persistent Kamilya Test & Evidence Runner
- Packet SHA: `2ef3afdda938127f17dc7edaff7ef4c23dd1551e`
- Runtime identity: root supplied independent readback for fixed release
  `f71da2a0af9da4c94c82622450cc78daa7ad22b8`; browser health/SHA readback was
  `NOT VERIFIED` because direct public health navigation was blocked by the
  browser client. Root supplied `kz-production`, image `kamilya-api:f71da2a0af9d`,
  zero worker restarts, and Alembic `0134`.
- Scope: exact Plus tenant only; resumed existing indexed document and published
  service-standard course; no regeneration or publication repeat.
- Matrix:
  - Existing group membership: `PASS`; exactly two synthetic members saved;
    visible count `2 участника`; toast `Состав группы сохранён`.
  - Second group: `PASS`; one group created for the other branch with two
    synthetic members; visible count `2 участника`; same success toast.
  - Individual course assignment: `PASS`; one synthetic learner assigned using
    personal link/PIN; visible status `Записан`, access active, notification
    `Не требуется`.
  - Learner journey: `PASS_WITH_FOLLOW_UP`; all 6 lessons reached `6 из 6
    уроков (100%)`; all 6 assessments returned visible `100%` and
    `Тест пройден!`.
  - Group course assignment through learning program: `BLOCKED`; two identical
    visible failures, `Не удалось сохранить` / `404: Learning program not found`.
  - Certificate: `BLOCKED`; learner Certificates page showed no issued
    certificates. Result confirmation remained `Ожидает подтверждения`; the UI
    stated electronic confirmation is unavailable without email and offered
    manual PDF confirmation.
  - Menu audit: `PARTIAL`; safe route traversal began, but the browser session
    timed out before complete coverage. No menu mutation was performed.
- Failure classification: `PRODUCT_DEFECT` for the learning-program save/publish
  path after two materially identical failures; dependent group assignment was
  not retried.
- Evidence labels: `RUNTIME-DERIVED` for visible production UI state;
  `PROVIDER-CONFIRMED` only for root-supplied independent runtime readback;
  `NOT VERIFIED` for browser health/SHA.
- Mutations: two group membership saves, one second group, one individual course
  assignment with personal access, synthetic learner lesson/test completion, and
  resulting progress/test records. No email or notification was sent.
- Cleanup: no duplicate or accidental artifact identified; successful Plus demo
  state preserved. No source fixture remained locally.
- Root review: group-program failure escalated through the required root thread;
  ledger entry is sanitized and append-only.

## RUN-20260828-PLUS-FULLFLOW-02 — fixed-release assignment retest addendum

- Runtime: root independently verified `kz-production`, exact SHA `4f694f02a99eb0215bc9b8f352be886fb10a75f8`, matching API/worker image, zero restarts, and Alembic `0134` (`PROVIDER-CONFIRMED`).
- Program/group assignment: `PASS`; exactly one normal UI assignment attempt succeeded with `Программа назначена`. The published v1 one-course program read back two active synthetic assignments from the Алматы group; no duplicate assignment or published program observed.
- Learner/result readback: `PASS_WITH_GATE`; training journal showed the completed synthetic learner at 100% progress and 100% best score, with status `В процессе` / `Ожидает подтверждения`. The normal confirmation UI requires a signed PDF/JPEG/PNG scan; no artifact was fabricated, uploaded, or signed.
- Menu/help audit: `PASS_PARTIAL`; training journal route loaded, Russian purpose/actions were understandable, and its help dialog opened and closed safely. Broader menu audit remains partial.
- Cleanup: none; demo-ready Plus state preserved. No email, other tenant, real-person data, direct API/DB, code, deployment, or provider action.

## RUN-20260828-PLUS-FULLFLOW-02 — narrow retest addendum (release 8f53120)

- Environment / exact SHA: `kz-production` / `8f53120a32f0fd91013968d45e9464d706645210` (`PROVIDER-CONFIRMED`, root independent runtime readback: public health exact SHA, API and three workers image `kamilya-api:8f53120a32f0`, zero restarts, Alembic `0134`).
- Scope: exact Plus tenant, methodologist UI; no other tenant, direct API/DB, code, deploy, provider, or mail action.
- Program save: `PASS`; reused the first preserved draft, added the existing published service course, saved successfully; visible toast `Траектория сохранена`.
- Program publish: `PASS`; exactly one selected draft became `Опубликована`, v1, 1 курс. Two identical pre-existing drafts were observed from the prior interrupted run; no new duplicate was created.
- Group-targeted program assignment: `FAIL / PRODUCT_DEFECT`; publication succeeded but automatic assignment failed once with visible `Программа опубликована, но назначение не выполнено` / `Internal server error`; current assignments visibly showed none. No unchanged retry performed.
- Group reconciliation: `PASS`; first group remained at 2 synthetic members; second group saved as the other 2 synthetic members, visible counts `2 участника` for both; toast `Состав группы сохранён`; first group readback confirmed its original 2.
- Remaining learner confirmation/certificate and full menu audit: `NOT RUN` in this narrow continuation after the assignment defect; prior learner completion evidence remains unchanged.
- Cleanup: none; successful Plus demo artifacts preserved. No identifiers, links, PINs, emails, or real-person data recorded.
