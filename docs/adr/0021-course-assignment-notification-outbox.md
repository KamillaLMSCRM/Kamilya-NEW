# ADR-0021: Manual course assignments use a durable email outbox

## Status

Accepted for incremental implementation.

## Decision

Every new manual course enrollment for a learner with an email creates one
tenant-scoped notification outbox row in the same database transaction. The
row is idempotent per enrollment; email delivery is attempted only after that
transaction commits. PostgreSQL `SECURITY DEFINER` claim/finalize/due functions
with RLS tenant-context checks own state transitions, so duplicate Celery work
and broker outages cannot lose committed work. Each provider request uses the
stable outbox id as Resend's `Idempotency-Key`; a crash after provider
acceptance can therefore be retried within the provider's 24-hour idempotency
window without sending a second message. The recovery timer runs every minute,
well inside that window.

Existing active accounts receive a course link. A learner without login access
may receive the existing pending activation link with course context; the
notification flow never creates a second invitation. Missing email or missing
prepared activation is recorded as a terminal visible delivery state.

The methodologist assignment list is the eventual delivery-status source of
truth and supports an explicit resend that requeues the same outbox record.
Tenant admin does not own this workflow.

The notifications worker restores transaction-local tenant context after the
claim commit before reading enrollment, learner, course or invitation data.
Unconfigured email defers without consuming retry budget. Activation delivery
uses only an existing, pending, unexpired invitation; active accounts receive
the configured `PUBLIC_URL` course link. A minute systemd timer runs the bounded
recovery entry point directly, independent of the Celery broker.

## Consequences

The enrollment transaction remains independent from Resend and Celery. A
broker-independent bounded recovery timer must invoke the due sweep in
production. API/UI integration is intentionally deferred until the concurrent
assignment-access flow is complete.
