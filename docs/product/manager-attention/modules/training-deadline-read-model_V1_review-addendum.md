# R1 V1 review addendum — 2026-09-05

Parent contract: `training-deadline-read-model_V1.md` (unchanged).

## Accepted edge semantics

- An enrollment is completed if its status is `completed` OR its completion
  timestamp exists. Missing completion time cannot establish punctuality:
  deadline status is `not_applicable`, never `overdue`.
- Direct cycle statuses `assigned` and `completed` are eligible. Path cycles
  require both cycle and path assignment to be active/completed. Skipped,
  cancelled or not-yet-active cycles retain their metadata but have
  `not_applicable` deadline status. They do not generate attention/reminders.
- Row classification and overdue predicates use the same SQL expression and
  database transaction clock. Equality at the deadline is not overdue; equality
  of completion and deadline is on time.
- Final pagination tie-break is enrollment identity, including repeated cycles
  of the same course for the same learner.
- Enrollment, user, course, occurrence and path links have explicit tenant and
  participant constraints in addition to existing RLS.
- Legacy frontend payloads with missing/null/unknown deadline fields must not
  display a reassuring deadline badge.

Non-recurring path-assignment deadlines remain outside R1 V1. Do not put a
mutable one-time assignment deadline into `cycle_due_at`. A later extension
requires an explicit provenance-aware deadline contract.

## Bounded scope impact

Root owns repository/policy fixes, unit tests, and this addendum. Terra owns
behavioral UI tests and, in a separate serialized packet, reporting integration
tests. Luna provides independent review. No migration or delivery is added to R1.

`scripts/ops/training_log_dev_check.py` is an additional root-owned verification
entrypoint. It verifies the canonical Supabase DEV identity before running only
the synthetic training-log suite through existing outer-transaction/savepoint
rollback fixtures. No production connection, schema change, provider delivery,
local PostgreSQL, or billable resource is permitted. Runtime-role checks must
assert `lms_app` without superuser/BYPASSRLS and restore the session role.

## Acceptance

Real PostgreSQL row/filter/count parity, terminal-cycle exclusions, completed
without timestamp, path-cycle provenance, stable pagination, and runtime tenant
isolation; focused backend/frontend tests and existing quality baselines.
Local success is not production release or email delivery evidence.
