# Training deadline read model V1

## Identity

| Field | Value |
|---|---|
| Module ID | `KML-MANAGER-ATTENTION-READ-001` |
| Name | Training deadline read model |
| Status | Accepted for implementation |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Owner direction: «план и реализация», 2026-09-05 |
| Change control | proposal -> root review -> implementation -> verification |
| Owning epic | Manager attention contour |

## Responsibility [Core]

Concentrate the read-only policy that connects an enrollment to its direct
course cycle or parent learning-path cycle and reports its effective deadline.

## Non-responsibilities [Core]

- Does not create, update, skip or complete an assignment or cycle.
- Does not send reminders or choose escalation recipients.
- Does not infer employee competence from course completion.
- Does not change evidence, certificate or quiz-attempt ownership.
- Does not assign statutory meaning to an internal deadline.

## User-visible contribution [Core]

The canonical training log shows the effective cycle deadline, distinguishes
active, overdue, completed-on-time and completed-late records, exposes an
`overdue` filter and exports the same facts to CSV.

## External interface [Core]

```text
GET /api/v1/admin/training-log?status=overdue -> TrainingLogPage
GET /api/v1/admin/training-log/summary       -> TrainingLogSummary(overdue)
GET /api/v1/admin/training-log?format=csv    -> matching deadline columns
```

Existing callers remain compatible: all new row fields have deterministic
defaults and the new summary count is additive.

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | `TrainingLogFilter` | V1 additive | status is one of assigned/in_progress/completed/overdue | tenant-scoped identifiers |
| Output | `TrainingLogRow` | V1 additive | cycle fields are null together for legacy rows | employee identity already owned by training log |
| Output | `TrainingLogSummary` | V1 additive | overdue is a subset of non-completed rows | aggregate only |

## Data ownership [Core]

This module owns no table and performs no writes. It reads `enrollments`,
`recurring_learning_assignments`, `learning_path_assignments` and
`learning_path_cycle_instances` through the existing tenant-scoped session.
Every cycle join includes matching `tenant_id`; existing RLS/FORCE RLS remains
the final database guard.

## Invariants [Core]

- A legacy enrollment without a cycle has `deadline_status=not_applicable`.
- An unfinished enrollment is overdue only when its effective due date is
  strictly earlier than database/current UTC time.
- Completion at the exact due time is on time.
- A completed enrollment is never returned by `status=overdue`.
- A direct course occurrence takes precedence over a path occurrence; an
  enrollment cannot legitimately belong to both.
- Overdue count is a subset and is never added to `total`.
- The CSV and JSON read models use the same rows and deadline policy.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| no deadline | read | not_applicable | no linked cycle due date | none |
| open | read | active | now <= due and not completed | none |
| open | read | overdue | now > due and not completed | none |
| any | read | completed_on_time | completed_at <= due | none |
| any | read | completed_late | completed_at > due | none |

## Error modes [Core]

| Error | Permanent/transient | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| Unsupported status | permanent | HTTP 422 | after correction | validation response |
| Missing cycle link | permanent data state | treat as not applicable | no | null cycle fields |
| Database unavailable | transient | existing training-log error | bounded by caller | request failure |

## Dependencies and adapters [Extended when applicable]

Not applicable. All dependencies are in-process SQLAlchemy models inside the
existing training-log implementation; no hypothetical port is introduced.

## Forbidden dependencies and side effects [Extended when applicable]

- No provider, broker, email, LLM, storage or credential access.
- No production, database, notification or evidence mutation.
- No local Docker PostgreSQL.

## Existing-module impact addendum [Extended when applicable]

| Affected module | Existing contract | Change | Compatibility | Regression test |
|---|---|---|---|---|
| training log backend | assigned/in_progress/completed read model | additive cycle/deadline fields and overdue filter/count | existing fields and filters unchanged | backend policy, CSV and integration contracts |
| training log frontend | one canonical reporting screen | additive deadline column, overdue card/filter | legacy rows show no deadline | Vitest source/translation/query contracts |
| recurring learning cycles | owns immutable occurrences | read-only joins only | no write or state transition | existing recurring suites |

## Security and privacy [Core]

Only existing reporting roles may call the routes. Tenant filtering remains
mandatory in the base query and in every new join. No new PII is introduced;
deadline data is exported only through the already protected training-log CSV.
No raw PII is logged.

## Observability [Extended when applicable]

The visible evidence is the row deadline status and aggregate overdue count.
No new telemetry containing employee data is added in V1.

## Verification [Core]

| Level | Scenario | Test/evidence | Required result |
|---|---|---|---|
| Unit | UTC deadline policy | `test_training_log_deadline_policy.py` | PASS |
| Interface | overdue query and additive schema | training-log integration contract | PASS on approved PostgreSQL |
| Contract | frontend query, column and locale keys | `trainingLog.test.ts` | PASS |
| Database | tenant-safe joins | existing RLS plus exact integration test | PASS in CI/Supabase DEV |
| Neighbor | recurring occurrence behavior | focused recurring backend/frontend suites | PASS |
| Integration | canonical training-log read | API integration test | PASS on approved PostgreSQL |

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | training log, learning cycles, learning paths, enrollment models |
| Write scope | training-log backend/frontend/tests, locale files, this mini-spec |
| Forbidden scope | migrations, notification writes, providers, production, unrelated dirty files |
| Required checks | focused backend unit, frontend Vitest, Ruff, frontend typecheck; DB integration only on approved contour |
| Stop conditions | migration becomes necessary; existing row ownership is ambiguous; tenant-safe join cannot be expressed |
| Handoff evidence | changed files, focused test counts, unverified DB/runtime gates |

## Rollout and rollback [Extended when applicable]

No schema migration or feature flag is required. Rollback is an application
rollback; stored cycle and enrollment data remains unchanged.

## Definition of Ready [Core]

- Responsibility, non-responsibilities and additive interface are explicit.
- Existing cycle identity fields support the read model without migration.
- Tenant-safe join and status invariants are testable.
- Write scope is bounded to previously clean files plus new artifacts.

## Definition of Done [Core]

- JSON, summary, filter, UI and CSV expose the same effective deadline.
- Focused no-DB checks pass.
- Approved PostgreSQL integration is either passed or explicitly left as a
  release gate; it is never replaced by mock evidence.
- No notification or production state changes are made.
