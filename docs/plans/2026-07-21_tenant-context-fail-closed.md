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
