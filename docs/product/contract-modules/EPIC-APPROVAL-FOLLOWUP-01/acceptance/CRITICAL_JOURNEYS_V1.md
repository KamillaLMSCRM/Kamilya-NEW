# EPIC-APPROVAL-FOLLOWUP-01 critical journeys V1

## CJ-01 Internal reviewer notification

In a disposable DEV tenant, assign one internal reviewer. Confirm one inbox row,
one unread badge, safe deep link and mark-read readback. Confirm no enrollment,
certificate or training-evidence record.

## CJ-02 Reminder without PIN

Schedule pending review inside threshold and run recovery twice. Capture the
typed email-adapter call: exactly one reminder, existing action URL, no PIN/token
in arguments/body/log/audit, and no credential change.

## CJ-03 Overdue escalation

Move pending work past due and recover twice. Confirm one overdue state, one
reviewer notice, one requester/methodologist escalation, and no copied reviewer
email as escalation recipient.

## CJ-04 Terminal suppression

For approved, changes-requested, cancelled, superseded and revoked cases,
recover and confirm no new actionable follow-up or reopened state.

## CJ-05 Tenant isolation

Tenant A lists/reads own notifications, then attempts tenant B ID. Confirm
non-disclosure and unchanged tenant B row against remote DEV Supabase using a
runtime-equivalent non-BYPASSRLS role.

## CJ-06 Neighbor regression

Run existing learner course/path notification, review credential, auth refresh
and queue-registration tests. Task names, queues, retries and invitations remain.

## CJ-07 Worker crash and persisted-data safety

Interrupt a claimed delivery before dispatch and confirm the expired lease is
discoverable by recovery. Confirm an exhausted stale claim becomes terminal.
Attempt to persist an extra `pin`/`token` context key, external URL and traversal
path; each write must fail at the database boundary.

## Production acceptance

After DEV/CI gates and exact authority, apply additive migration; deploy API,
notification worker and web; independently read back Git/provider/schema/worker
revisions; perform one bounded synthetic internal-review notification; close or
remove synthetic state and report evidence.
