# ADR-0019: Recurring learning cycles are immutable delivery instances

> Implementation note (2026-08-09): migrations 0098 and 0103 implement native
> recurring courses with a distinct enrollment per immutable occurrence.
> Progress, quiz attempts, evidence, certificates and training-log reads are
> enrollment-instance scoped. Legacy grants retain NULL-scoped compatibility.
> SCORM recurrence remains blocked until SCORM attempts gain the same identity.

## Status

Accepted for incremental implementation.

## Context

Kamilya supports versioned learning programs with optional start and due dates,
and it materializes course access through `enrollments`. It does not yet support
recurring annual or periodic requirements, per-learner deadline changes, or
reminders. `Enrollment` is both the access record and an evidence anchor: a
completed row, linked release, quiz attempts, certificate and append-only
training evidence must remain historically correct.

Reopening or editing a completed enrollment would lose the distinction between
two compliance periods. Reusing `LearningPathAssignment` is also incorrect:
its `(path_id, user_id)` uniqueness and mutable lifecycle describe one current
program delivery, not a succession of immutable cycles. The existing
`positions.assignment_service.recompute_enrollments` is the assignment kernel
for organization, department and position rules and must not be repurposed for
time-based recurrence.

## Decision

Introduce a separate, methodologist-owned learning-cycle domain.

- A tenant-scoped cycle template declares a published course or a published
  learning-path version, recurrence calendar, timezone, due-date policy and
  reminder policy. Changes apply only to future cycle instances.
- A cycle instance is a dated immutable copy of that template. It has a stable
  sequence number and a frozen target version/release.
- A participant record is created per selected learner per instance. It stores
  audience provenance and the effective start/due dates. A documented,
  reasoned per-user override changes only that participant and is recorded in
  an append-only participant-event stream.
- Reminder delivery has its own tenant-scoped idempotency ledger. A unique
  participant/reminder/channel key is claimed before a notification is queued
  or sent. Duplicate scheduler ticks and Celery delivery are therefore safe.
- Course cycles issue a distinct cycle-linked enrollment. Before that is
  enabled, completion, attempt, progress, certificate and training-log paths
  must be made unambiguous by enrollment instance. The existing global
  learner-course unique constraint cannot be relaxed until this gate is met.
- Program cycles use immutable learning-path versions and cycle-linked child
  enrollments; they do not reactivate or overwrite `LearningPathAssignment`.
- The training log gains cycle instance and effective due-date fields, and may
  show `overdue` only for cycle participants. Legacy enrollment rows remain
  deadline-free.

The canonical methodologist UI is `/learning-cycles`. Learners continue to use
their existing course and `/learning-paths` surfaces, augmented with their
effective due date. `/training-log` remains the canonical history/reporting
surface. Tenant admin does not receive a cycles workflow.

Every new tenant-scoped table requires `tenant_id`, backend ownership checks,
RLS, `FORCE ROW LEVEL SECURITY`, runtime `lms_app` access without
`BYPASSRLS`, and cross-tenant tests. The scheduled worker uses UTC for task
execution but computes periods in the template's declared timezone.

## Consequences

- Completed periods and their evidence remain immutable while a later period
  can require the same course again.
- Existing manual, organization, department, position, cohort and learning-path
  grants remain independent; closing a cycle never revokes an unrelated grant.
- The implementation requires an explicit enrollment-instance compatibility
  phase before recurring course delivery, rather than a risky schema-only
  shortcut.
- Reminder operations require a real periodic scheduler/timer, notification
  queue registration, bounded retry and stale-claim recovery in addition to
  API deployment.
