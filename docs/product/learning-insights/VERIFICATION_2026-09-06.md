# LEARNING-INSIGHTS-01 verification

Status: implementation candidate; not a production release. Base
`5c297eb99c64834aac3f5b57628d017a1006f644`, branch
`feat/learning-insights-20260906`, isolated worktree `learning-insights`.

## Verified backend and database

- Focused backend/evidence/journal/quiz regression: 35 passed.
- Python quality baseline: passed, Ruff 1091 / mypy 2356; no baseline relaxation.
- Alembic offline revision discovery: single head `0155`, parent `0154`.
- Required AI-COURSE-01 database-free assertions: 4 API tests + 1 CI contract test passed.
- Required document reindex/idempotence assertion executed by name from its
  existing integration test against synthetic isolated DEV fixtures; passed.
  Storage and ingestion remain stubbed by that test; this is not an LLM/provider smoke.

Supabase DEV gate completed successfully in `li_dev_9464ce4faa9b`:

Final repeat after the backend review/typing/ownership corrections also passed
all 14 groups in `li_dev_7c0c08e7cf13`; exact schema cleanup and unchanged shared
migration head were independently read back again.

1. Upgrade, downgrade and reupgrade of actual migration 0155.
2. Synthetic-only fixtures, no copies of tenant data.
3. Enrollment HTTP detail, exact selected/key answers, release lesson identity.
4. Unique-first/latest statistics and first-completion period selection.
5. Foreign enrollment/course 404; no email, phone or credential fields returned.
6. Student/admin/inactive/platform-no-tenant 403; tenant-scoped authorized access.
7. Repeated status PUT, unique row, fresh-session persistence, foreign PUT 404.
8. Original attempt evidence hashes unchanged.
9. RLS and FORCE RLS; absent/foreign context cannot read annotations.
10. Runtime cross-tenant/course/actor writes denied; invalid status and DELETE denied,
    checked against PostgreSQL SQLSTATE 42501 / 23514.
11. Aggregate/history overflow produces 422 rather than partial success.
12. Missing first cannot be replaced by retry; missing/different latest is unknown.
13. Actual latest cutoff by date_to and null percentage when no latest is comparable.
14. Exact required document-worker regression.

Cleanup readback: the exact disposable schema is absent. Shared
`public.alembic_version` remained unchanged. Database runtime identity was
`lms_app`, without superuser or BYPASSRLS. No local Docker PostgreSQL, public data
writes, provider changes, new paid resources, migration of shared DEV/public, or
production actions were used.

One earlier expanded test-harness run failed because its synthetic schema lacked
`document_embeddings`, required by the existing document-worker test. That exact
schema (`li_dev_607f3ee888d4`) was removed with readback; the schema-only allowlist
was corrected, and the expanded gate passed. This was a harness failure, not a
passing worker test. First LI-only gate also passed and cleaned `li_dev_ef732dd35338`.

## Review and delegation

- Backend: gpt-5.6-terra/high; frontend: gpt-5.6-terra/medium.
- Independent review: gpt-5.6-terra/high, read-only, not the author.
- Bounded frontend repair: gpt-5.6-luna/high.
- Root owns contracts, migration, integration, adjudication and acceptance.
- No agent had permission to install dependencies, inspect secrets, mutate provider
  state, commit/push, or use real tenant data. Agent communication was English.
- First review found real date-contract, stale-tenant UI, latest-evidence projection,
  row-role and accessibility defects despite initially passing focused tests.
  Corrections and regression tests are part of this candidate, not follow-up promises.
- Exposed per-worker token/cost counters: unavailable; do not interpret as zero.

## Graph and frontend evidence

- Graphify AST-only extraction: 1,253 code files, 15,268 nodes, 36,455 edges;
  no document/LLM extraction. Derived files remain ignored and local.
- Graph diagnostics: zero dangling endpoints, self-loops or exact duplicate edges.
  Fourteen data/config files produced no code nodes; this is not proof of complete
  semantic coverage or of unused code. Post-build graph is undirected.
- Representative queries for get_course_insights and LearningInsightsPanel match
  current source locations and the accepted module map (journal/auth/API, existing
  attempt/enrollment/course/release/position readers, annotation writer).
  Query budgets were intentionally bounded; truncated results are not absence proof.
- Repaired feature + training-log helper suite: 25 tests passed (2 files).
- Root full-journal render regressions: 3 passed (empty-page catalog, role/hook
  transition, tenant catalog isolation).
- Final frontend TypeScript check passed.
- The initial full frontend run was stopped after a worker accumulated CPU/memory
  without completing. A per-module diagnostic narrowed the cause to
  trainingLogDeadlineView.test.tsx; a single legacy-row test also reproduced the
  hang. Making its mocked translation callback stable (matching real useT) made
  the same case pass in ~2 seconds. Deadline assertions were preserved; the mock
  now also acknowledges the new catalog route. See ERRORS.md TEST-011.
- Final focused frontend rerun: 35 tests passed across four files.
- Original full-suite scenario rerun after the fixture correction: **104 files,
  533 tests passed**, 88.78 seconds, maxWorkers=2. No test was disabled. Temporary
  per-module diagnostic reporter was removed after the successful run.

## Independent acceptance and remaining release work

- Final independent backend and UI/API role-and-race reviews: PASS, no remaining
  concrete blocker in the reviewed delta. The reviewer was read-only and separate
  from implementation. Canonical `/training-log` reexports the integrated journal.
- Browser smoke under a real authorized synthetic methodologist session has not run.
- No feature commit, push, CI run, provider document-to-course smoke, backup/release
  gate, frontend/API deployment or production readback is claimed.

Final acceptance corrections: direct active-superadmin access was an overbroad
root assumption, not an existing permission. The full-page role test exposed
the discrepancy. ACTIVE_ROLE_ADDENDUM_V1 restores ADR-0012: methodologist-only
API/UI; authenticated methodologist impersonation remains available. No registry
or role capability was broadened. A deferred dual-mounted-control test also
failed before shared same-key mutation serialization and passed after it.
The original 533-test result precedes these final corrections; their rerun is
recorded below when complete.

## Final candidate reruns

- Full frontend after final role/serialization fixes: **104 files, 535 tests passed**,
  86.70 seconds, maxWorkers=2. Focused feature/journal subset: 37 passed.
- Final TypeScript check passed.
- Final backend/evidence/journal/quiz regression: 35 passed.
- Final independent role/race source acceptance: PASS, no remaining concrete blocker.
- Final incremental Graphify extraction: 8 changed files, 1,245 unchanged, no deleted
  sources; 15,280 nodes / 36,304 edges. Diagnostics remain clean. Counts differ
  from the earlier full rebuild; graph output is derived and not a lossless call graph.
- Final DEV-role gate: **PASS**, all 14 groups, schema `li_dev_4bd3f7ab93ad`.
  Exact-schema cleanup and unchanged shared migration head read back successfully.
  Final guards reject active student/admin/superadmin on all new endpoints;
  authenticated active-methodologist impersonation still saves successfully.
- Final Python quality baseline remains PASS (Ruff 1091 / mypy 2356); final
  whitespace/diff check passed. Primary checkout still has its pre-existing
  108 dirty entries; this candidate remains isolated with no feature commit/push.

## Owner-approved documentation correction

The owner explicitly approved the narrow framework correction in the continuation.
PROJECT_INTERNAL_DOCUMENTATION.md now names Next.js 15.5.23, matching the exact
apps/web/package.json dependency. Luna made the one-line change; root reviewed
the exact diff and preserved the existing candidate section and freshness date.
This is a version correction, not a blanket documentation re-audit.

## Release-continuation evidence

- RUNTIME-DERIVED: root reran the unchanged isolated DEV gate against canonical
  Supabase. All 14 groups passed in `li_dev_d9e4dce570c1`; exact schema cleanup
  and unchanged shared migration head were confirmed. No public/production writes.
- PROVIDER-CONFIRMED: KZ and Render public health identify exact
  `676fee152b5b052aabbacedc27d624b5987f295b`, with environments `kz-production`
  and `render-development` respectively. Render is free, one instance, not
  suspended, dev branch, autoDeploy enabled, live deploy `dep-daefcf5bedkc73d3eclg`.
- GIT-DERIVED: canonical project-account remote readback confirms master
  `5c297eb99c64834aac3f5b57628d017a1006f644` and dev `676fee15...`.
- PROVIDER-CONFIRMED: Vercel web production deployment
  `dpl_2dGsf82wP2uBQ7qsQfF1VYzWLwiU` is READY on exact master5c297eb9.
  Recent cancelled dev preview builds are not the stable alias identity.
- Release Runner identified master auto-deploy ordering risk. Root chose separate
  backend-only and frontend source packages, retaining old UI until API0155 has
  passed production acceptance. No provider hold/settings change is approved.
- Test Runner owns local full tests/build/typecheck evidence; fresh browser and
  publication evidence remain NOT VERIFIED. Exact temporary CT125 restore target
  `kamilya_li_restore_20260906` awaits new owner approval; earlier buyer-drill
  permission is not reused.

Local release acceptance `LI-LOCAL-RELEASE-20260906` and correction `-R1` are
recorded append-only in docs/testing/TEST_RUN_LEDGER.md. Frontend104 files/535
tests PASS, production build62/62 pages PASS, sequential typecheck PASS, backend
focused35 PASS. Source manifest19 files was unchanged across verification.
R1 quality PASS (Ruff1091/mypy2356), release contract PASS (head0155) and diff
check PASS. Root corrected the new journal-entry header date, not a product test.
Runtime routing correction: root .venv supplies these backend runtime tests;
primary apps/api/.venv supplies existing Ruff/mypy, explicitly verified before
use. No packages installed and no baseline relaxed.

Operational residual: Test Runner accidentally created an empty Poetry environment
`api-eEQ5pG_A-py3.12`. Root verified the exact non-link path/creation time and
bootstrap-only contents, but tool policy rejected cleanup before execution.
The residual is documented in the ledger, is outside the release source tree,
and is not used. No alternate deletion method attempted.

DEV release progression: shared canonical Supabase DEV migrated0154->0155 with
empty annotation table and FORCE RLS; exact dev91ce518c pushed/read back on
2026-09-06T10:36:14Z. Delegated access failed locally; root's same canonical path
succeeded. Production master/API were not changed. CI34027881507 passed every
backend/DB/RLS/security job but failed strict frontend lint on two hook warnings.
Terra repaired only callback-filter construction and primitive review reset state,
plus one equivalent-rerender regression. Focused17 tests/strict lint/typecheck
passed and root reviewed the narrow diff; no suppression or contract weakening.
The replacement commit must pass fresh CI before DEV business acceptance.
Root independently logged in through the real DEV browser password form using
only existing dedicated DEV credentials; no password reset or secret output.
