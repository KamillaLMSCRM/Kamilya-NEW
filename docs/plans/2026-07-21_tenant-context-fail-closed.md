# Tenant-context fail-closed and course approval workflow

## Plan

- [x] Inspect repository guidance, Graphify-selected tenant/auth/review seams, git state, and existing implementation.
- [x] Make tenant-context setup fail closed and add regression coverage for rollback/no ORM access.
- [x] Harden reviewer isolation, immutable snapshots, lifecycle transitions, delivery retries, reminders/escalations, and audit/idempotency behavior.
- [x] Run targeted, unit, lint, compile, and DEV-only migration/RLS checks; record blockers without touching production.
- [x] Review the final diff, commit the isolated branch, and report exact verification and residual risks.

## Safety boundaries

- No production database, DNS, deployment, provider billing, push, or secret-value inspection.
- Every ORM query in this workflow carries tenant scope; reviewer links are capability-scoped and fail closed.
- `graphify-out/` remains untracked.

## Evidence log

- Graphify context search was run before broad code exploration and selected the course approval/release, auth/RLS, reviewer attempt, delivery, and backend test seams.
- Prior targeted and unit checks passed; full unit has one unrelated pre-existing documentation-date failure; DB-backed integration is unavailable without a local database.
- DEV Alembic advanced from `0146` to `0147` through the Supabase pooler using runtime role `lms_app`; all twelve workflow tables exist with RLS and FORCE RLS enabled, one tenant policy each, and zero rows. No production endpoint or database was accessed.
- DEV-only downgrade/upgrade of the empty `0147` workflow surface succeeded; catalog readback found both SECURITY DEFINER due-selector functions owned by `postgres` with `lms_recovery` EXECUTE ACLs. Runtime-role readback remains `NOSUPERUSER`/`NOBYPASSRLS`.

## Follow-up hardening plan (post-review)

- [x] Add strictly scoped request list/detail projections and non-enumerating cross-scope behavior.
- [x] Make `decision_pending` and server-derived checkpoint/test completion first-class.
- [x] Separate requester/admin and scoped-reviewer projections; cover mixed guest/internal reviewers.
- [x] Settle resend/rotation, reusable credential semantics, personal-link reminders, terminal delivery filtering, and audit events.
- [x] Complete actor/recipient tenant integrity, append-only delete denial, safe migration downgrade, kill-switch publication semantics, and idempotent unpublish.
- [x] Run targeted/full tests and repeat DEV-only migration/RLS evidence, then commit the follow-up.

## Independent-review findings (completed)

- [x] Scoped reviewer request list/detail and non-enumerating cross-scope behavior.
- [x] First-class `decision_pending`; server-derived completion/checkpoint state.
- [x] Separate rich requester/scoped-reviewer DTOs and mixed guest/internal coverage.
- [x] Explicit resend retry versus credential rotation; reusable credential semantics.
- [x] Personal-link reminder routing and terminal delivery state/filtering.
- [x] Attempt/progress/test audit events and actor/recipient tenant integrity.
- [x] Append-only delete denial, safe downgrade refusal, forward kill-switch rollback, and idempotent unpublish.

## Forward rollback policy

The runtime kill switch blocks only new approval-workflow writes; historical reads and scoped reviewer state remain available. It never bypasses a required approval gate at publication. Database downgrade is refused when workflow rows exist; rollback is forward-only unless an explicitly approved empty-DEV rollback is performed.

## Follow-up verification

- Targeted contract/auth/tenant tests: `33 passed`.
- DEV-only runtime-role integrity tests: `2 passed`; cross-tenant actor and recipient references were rejected by the database trigger.
- Full unit suite: `854 passed, 1 failed`; the sole failure is the pre-existing release-journal date contract (`docs/ERRORS.md` header does not match its latest entry), outside this change set.
- Static verification: Ruff (`F,E9,I`), Python compileall, and `git diff --check` passed.
- DEV migration/catalog readback: Alembic `0147 (head)`; `lms_app` is `NOSUPERUSER`/`NOBYPASSRLS`; all 12 workflow tables have RLS+FORCE RLS; delete is denied on append-only revision/request/attempt/event tables; both recovery selector functions exist with `lms_recovery` execute ACL; workflow tables contain zero rows.
- No production DB/DNS/deploy/push/provider mutation was performed. Graphify was used before broad exploration in the parent pass and selected auth/RLS, course-approval/release, delivery, reviewer-attempt, and test seams; no callable graph refresh tool was exposed during this follow-up.
