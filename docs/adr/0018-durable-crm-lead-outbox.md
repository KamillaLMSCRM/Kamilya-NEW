# ADR-0018: Durable signed CRM lead outbox

## Status

Accepted for implementation. Production activation remains gated by migration,
worker/timer parity and an end-to-end delivery smoke.

## Context

Public landing leads and trial registrations are accepted by the LMS API, while
the operator works with them in Kamilya CRM. A synchronous CRM request inside
lead acceptance would make the public form depend on CRM, DNS and network
availability. Dispatching only through Celery after commit would lose the
notification when the broker is unavailable.

The payload contains contact data. The application database role therefore
must not receive ordinary table access to a global outbox, especially for
public leads whose `tenant_id` is `NULL`.

## Decision

PostgreSQL is the source of truth for delivery state.

- Lead and outbox rows are created in one transaction. The outbox primary key
  equals `lead_id`, and `event_id` is stable as `lmslead_<lead UUID without
  hyphens>`.
- The exact JSON bytes to be signed and sent are persisted once. Retries do not
  rebuild the payload.
- The table uses RLS and `FORCE RLS`, has no direct `lms_app` table privileges,
  and is accessible only through bounded `SECURITY DEFINER` functions with a
  fixed `search_path` and revoked `PUBLIC` access.
- A claim token serializes delivery. Finalization requires the same token.
  Duplicate Celery messages are harmless, while CRM also deduplicates by
  `event_id`.
- HTTP `2xx` is delivered; `429`, `5xx` and network failures retry with bounded
  exponential backoff and jitter; other `4xx` responses become terminal.
  Missing configuration defers without consuming the eight delivery attempts.
- Immediate Celery dispatch is only acceleration. A checked-in systemd timer
  calls the bounded Python recovery entry point directly every minute, so
  accepted leads survive broker or worker downtime without accumulating timer
  messages in the broker.
- Superadmin operations expose aggregate counts and a dry-run-first, bounded,
  explicitly confirmed requeue. They never return payload bytes or contact
  data.
- Requests are signed exactly as
  `timestamp_ms + "\n" + event_id + "\n" + event_type + "\n" + raw_body`
  using HMAC-SHA256 and the shared secret.

## Consequences

The public form remains available during CRM outages and accepted leads remain
recoverable. Deployment now requires coordinated LMS migration, API and worker
configuration, installation of the recovery timer, the same secret in CRM and
LMS, and an exact-byte end-to-end smoke. Changing an event payload requires a
new payload version instead of rewriting pending rows. Migration downgrade is
blocked while any outbox row exists; operators must export/archive the table,
verify the archive and explicitly clear it before a schema rollback.
