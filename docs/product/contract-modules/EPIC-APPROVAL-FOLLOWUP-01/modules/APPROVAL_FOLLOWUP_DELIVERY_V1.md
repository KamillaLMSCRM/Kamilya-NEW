# Approval follow-up delivery mini-spec V1

## Identity [Core]

Accepted; document/template V1/V2; epic `EPIC-APPROVAL-FOLLOWUP-01`; backend
module owner; product-owner approval inherited from epic; changes require V2 or
an impact addendum.

## Responsibility [Core]

Materialize one safe assignment, reminder or overdue delivery with deterministic
recipient, terminal suppression, idempotency and retry classification.

## Non-responsibilities [Core]

No approval decisions, inbox read state, frontend, learner notifications,
provider configuration, billing or credential rotation.

## User-visible contribution [Core]

The right person receives a timely action. Reminder/escalation email reuses an
allowed link but never reveals or recreates a PIN.

## External interface and I/O [Core]

```text
deliver_workflow_delivery(tenant_id, delivery_id) -> status
recover_workflow_deadlines(limit<=100) -> counts
materialize_notification(WorkflowNotificationIntentV1) -> notification|no-recipient
send_course_review_reminder(..., access_url, due_at, idempotency_key)
send_course_review_escalation(..., action_url, due_at, idempotency_key)
```

Reminder/escalation signatures cannot accept PIN. Inputs are persisted,
tenant-bound deliveries with an allowlisted kind; outputs contain no secret.

## Data ownership, invariants and state [Core]

Approval retains delivery/reminder/escalation/deadline ownership; inbox writes
only through its public interface. Initial invitation may carry PIN; follow-up
never does. Escalation targets requester, not copied reviewer email. Terminal
work creates no action. Existing epic state machines remain canonical.

## Errors, security and verification [Core]

Missing binding/recipient/required action data is terminal. Existing transient
provider categories remain bounded/retryable. Tenant RLS is restored after each
commit. No secret/payload logs. Tests assert actual adapter arguments, recipient,
duplicate recovery, terminal suppression and learner-outbox negative space.
Each accepted claim persists a bounded lease. Recovery may reclaim an expired
lease, and an exhausted stale claim becomes explicit terminal evidence rather
than remaining accepted forever. A deadline row becomes delivered only after a
corresponding follow-up delivery has been queued.

## Implementation packet [Core]

Scope: approval service/models/worker, email service, additive migration and
focused tests. Forbidden: enrollment outboxes, provider settings and frontend.

## Extended requirements

Unique rule/source keys; `FOR UPDATE SKIP LOCKED`; existing retry limit and
bounded recovery. Safe kind/status/count telemetry only. Additive schema first;
kill switch rollback; no destructive downgrade.

## Ready and done [Core]

Ready when contracts, recipients, migration and tests are fixed. Done when
focused/contract/RLS/neighbor tests pass and graph has only expected edges.
