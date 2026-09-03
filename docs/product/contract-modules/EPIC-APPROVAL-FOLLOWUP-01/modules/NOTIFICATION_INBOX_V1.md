# Notification inbox mini-spec V1

## Identity [Core]

Accepted; document/template V1/V2; epic `EPIC-APPROVAL-FOLLOWUP-01`; backend
module owner; product-owner approval inherited from epic; changes require V2.

## Responsibility [Core]

Own durable, safe, tenant/user-scoped notification projection and read state.

## Non-responsibilities [Core]

No deadline/recipient calculation, email delivery, approval authorization,
credential storage or browser-derived workflow policy.

## User-visible contribution [Core]

Each signed-in user sees their own notifications and accurate unread count, and
can idempotently mark one or all as read.

## External interface and I/O [Core]

```text
materialize(intent V1) -> notification
GET /v1/notifications?limit<=50 -> {items, unread_count}
POST /v1/notifications/{id}/read -> notification
POST /v1/notifications/read-all -> {updated, unread_count: 0}
```

Only allowlisted kinds and relative action paths. Output is opaque ID, kind,
safe context, action path, read time and creation time, newest first.

## Data ownership, invariants and state [Core]

Owns inbox table and `unread -> read`. User sees/writes only own tenant rows. One
source delivery creates at most one row. Read state never changes workflow.

## Errors, security and verification [Core]

Unknown/cross-tenant ID is 404. Invalid kind/path fails closed. Duplicate source
returns existing row. RLS/FORCE RLS and server-derived tenant/user are required.
No external URL, HTML, PIN, token, encrypted payload, answer key or raw PII.
Tests cover DTO, idempotency, list/count/read, path allowlist and remote DEV RLS.
Database constraints admit only `course_title` and `due_at` context keys plus
the two versioned relative path forms. SELECT/UPDATE require both tenant context
and authenticated `app.user_id`; INSERT remains tenant-scoped and is tied by a
trigger to the source delivery recipient.

## Implementation packet [Core]

Scope: new notification package, registry/router registration, migration and
focused tests. Forbidden: approval policy, email provider and frontend.

## Extended requirements

Unique source delivery constraint; monotonic `read_at`; safe aggregate metrics;
additive migration and non-destructive rollback. Inbox must not import approval.

## Ready and done [Core]

Ready when intent/HTTP/RLS contracts are fixed. Done when focused/contract/RLS
tests pass and graph shows no forbidden reverse dependency.
