# Participant deadline history V1

Status: Accepted

## Responsibility and contribution

Own the original/effective deadline distinction and append-only reasoned events
for the single learner represented by an existing course occurrence or program
cycle instance. Existing occurrence rows are the V1 participant records; this
module does not introduce a competing template/participant hierarchy.

## Interface

- `GET /learning-cycles/occurrences?scope=latest|history`
- `POST /learning-cycles/occurrences/{target_type}/{occurrence_id}/deadline-override`
- `GET /learning-cycles/occurrences/{target_type}/{occurrence_id}/events`

Inputs: tenant-bound occurrence, timezone-aware effective due date, reason of
20-1000 characters. Outputs: exact occurrence projection or ordered event list.

## Data ownership and invariants

- Course occurrence and path cycle own frozen target, learner, sequence,
  schedule and original due date.
- `effective_due_at` is the only mutable deadline projection.
- Deadline events own prior/new effective dates, reason, nullable tenant author
  and creation time; events are insert/read only.
- Tenant key is server-owned. Target and actor ownership are enforced by API,
  RLS/FORCE RLS and DB checks/triggers.
- Completed, skipped or cancelled occurrences reject override.
- Sent/sending reminder history is immutable; queued/failed unsent delivery may
  be rescheduled without changing its idempotency key.

## Error modes

404 unknown/foreign occurrence; 409 terminal occurrence; 422 invalid date or
reason; DB conflict rolls back event, projection and reminder reschedule
together.

## Verification, scope and rollout

Public API tests, migration upgrade/downgrade, runtime-role RLS and cross-tenant
negative tests, training-log/reminder contract tests, UI journey. Additive
migration; older app ignores new columns/table. Downgrade refuses when events
exist. Read/write scope: learning cycles, reminder target/reschedule function,
training-log deadline projection, migration and owned tests. Stop on any need to
rewrite completion/certificate history or weaken RLS.
