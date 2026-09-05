# R2 delivery transport addendum V2 — existing SMTP

Accepted by root, 2026-09-05, within owner request to finish mailbox pilot and
production rollout. Supersedes only Resend-only restriction of V1 implementation
addendum; existing role, tenant, dates, retention and global-off defaults remain.
Evidence: canonical VM126 read-only preflight confirms EMAIL_PROVIDER=smtp;
public runtime SHA aaebce32580586f6109d80c6dd5aad542691348b. No provider switch.

## Contract and ownership

Delivery owns fixed transport provenance per outbox row, null before first
reservation, then resend/smtp. Begin-send gains optional p_transport text default
'resend' at SQL boundary and `transport='resend'` at Python store boundary.
First send reserves transport atomically with attempt/hash. Changing transport
after reservation fails terminally. SMTP permits ONE reservation total, including
crash after reservation: later recovery marks `delivery_uncertain`, never resends.
Resend keeps the existing max3/23h same-payload/key semantics. SMTP failure after
reservation is terminal (even a possibly pre-DATA failure); no automatic resend
or claim that stable Message-ID makes SMTP idempotent. Missing configuration
still defers before reservation/attempt budget.

SMTP success requires send_message() acceptance (empty refusal map); store its
stable generated Message-ID as delivery_message_id. This proves server acceptance,
not inbox arrival. Inbox receipt is separate browser evidence for owner pilot.
Message-ID derived from SHA256 of opaque reminder key; no PII or secret in it.
Existing non-reminder _send / _send_smtp callers retain their None return and
headers unless they explicitly opt into the reminder delivery contract.

Root: migration0152 (undeployed), store/worker, SQL/assembled gates, UI safe reason
labels, integration, docs and all external actions. Terra: email.py SMTP addition
and test_learning_reminder_email.py only. No shared writer. Reviewer read-only.
Tests: ordinary email regressions, SMTP accepted/refused/timeout, durable SMTP
one-reservation and stale-crash suppression, transport-change refusal, prior
Resend contracts, all three owner inboxes. Stop on provider/billing change or
required privilege expansion. Runtime activation is exact release-node action,
not implied by changing default config. Rollback keeps global flag off and
previous image; additive schema remains compatible, ledger is not downgraded.
