# Staff Sync API

Status: canonical contract. The single-event vertical slice is deployed to
Render dev at revision `0132` and release
`cf12ee260f0080ebcc4d70b440d4849bb70f8a10`. No real tenant credential has
been issued and no production activation is claimed.

## Scope and tenancy

The API synchronizes one external staff directory into exactly one Kamilya
tenant. Every request is evaluated against the tenant bound to the integration
token. A caller must not select or override a tenant through a request body.
The implemented single-event endpoint is:

```text
POST /v1/integrations/staff-sync/events
```

Credential management is available to a tenant administrator at
`/v1/integrations/staff-sync/credential`. The machine endpoint resolves the
tenant from the credential lookup function, sets database tenant context, and
uses FORCE RLS tables. Issuing a credential remains an explicit activation.

## Authentication and token scope

Use a dedicated, rotatable machine token, never a user session token. The token
must carry or resolve to:

- one immutable `tenant_id`;
- an integration identity (`client_id` or equivalent);
- scope `staff:sync` for the current event endpoint;
- expiry, revocation, and key/version metadata.

Tokens are tenant-bound and least-privilege. `staff:sync` does not grant
access to other tenants, users, courses, billing, provider keys, or arbitrary
admin operations. Log token identity and scope, never the token value.

## Request contract

The implemented event request is JSON and must include an `Idempotency-Key`
header exactly matching `event_id`:

```json
{
  "event_id": "event-001",
  "source": "hr-directory-example",
  "action": "upsert",
  "external_employee_id": "employee-001",
  "effective_at": "2026-08-26T10:00:00+05:00",
  "employee": {
      "personnel_number": "EMP-001",
      "first_name": "Example",
      "last_name": "Person",
      "email": "example.person@example.invalid",
      "position_external_key": "position-operator"
  }
}
```

The server rejects ambiguous matches rather than guessing. `source` identifies
the upstream system and is not an identity key. The example values are
synthetic and non-PII.

`dry_run`, batch input and `FULL_RECONCILIATION` are not part of the first
vertical slice. They remain gated follow-up work that must reuse the existing
proposal revision/hash approval invariants rather than bypassing them.

## External identity and matching

`external_employee_id` is the stable upstream identity and is required for this API.
It must be immutable for the life of the source connection. The existing LMS
staff-import seam matches records by normalized, tenant-local
`personnel_number` and the database migration enforces tenant uniqueness for
that field. Until a dedicated external-identity mapping exists, the adapter
must require a stable `personnel_number` and treat an external-id/personnel-
number mismatch as a conflict, never as a new employee.

Matching precedence:

1. source plus `external_employee_id` mapping;
2. normalized `personnel_number` within the bound tenant;
3. no email-only or name-only automatic matching.

Email and phone are attributes, not identity. Conflicting email, duplicate
personnel numbers, missing required identity, or an identity collision produces
an item-level conflict and no mutation for that item.

## Actions

Each planned item has exactly one action:

| Action | Meaning | Write effect |
| --- | --- | --- |
| `upsert` | Create a missing staff member or update an identified member | Create/update only the supplied, validated attributes; do not blank omitted optional fields |
| `terminate` | End employment in the tenant | Soft-offboard: set `is_active=false` and the agreed inactive/terminated status; retain the account and audit trail |
| `reactivate` | Restore a previously terminated member | Set `is_active=true` and status `active` only after an unambiguous identity match |

`upsert` may reactivate only when the source explicitly declares the member
active or the request uses `reactivate`; an ordinary partial update must not
silently undo offboarding. Role changes, invitations, password operations,
course data, and provider-side deletion are outside this contract.

## Dry-run and full reconciliation boundaries

The following is the required next phase, not current runtime behavior:
`dry_run: true` parses, validates, matches, and returns a deterministic plan.
It creates no users, does not change `is_active` or `status`, and does not
dispatch invitations or downstream provider calls. The response includes a
request fingerprint, idempotency key, mode, counts by action, item conflicts,
and a proposal revision/hash suitable for approval.

`dry_run: false` may execute only the approved proposal represented by the
same revision/hash. The proposal is immutable after approval; a changed source
payload requires a new idempotency key and new approval. The existing session
model provides `ADD_OR_UPDATE` as the safe default, explicit
`FULL_RECONCILIATION`, revision/hash fields, approval metadata, and guarded
state transitions. The sidecar should reuse those invariants rather than
inventing a second commit protocol.

`FULL_RECONCILIATION` means “the submitted source is authoritative for the
tenant and source connection.” Records absent from the authoritative active
set become planned `terminate` actions only. It must never be inferred from a
partial export, timeout, parser warning, or empty payload. Require an explicit
confirmation that absence means termination, plus review of the planned
termination count before commit. A partial/unknown export is rejected or
treated as `ADD_OR_UPDATE` with no implicit offboarding.

## Idempotency and concurrency

For the implemented event endpoint, `Idempotency-Key` must equal `event_id`.
For a tenant, source and event ID, one canonical payload hash is accepted. A
retry with the same hash returns the original result without repeating the
employee mutation. Reuse with a different hash returns `event_id_reused`.
Processing is serialized with a PostgreSQL transaction advisory lock for the
same tenant/source/event tuple, and the database uniqueness constraint remains
the final duplicate-write guard.

Batch sessions, dry-run proposals, proposal revisions and full reconciliation
remain future gates. If added, they should preserve the existing
`staff_import_sessions` idempotency and stale-proposal invariants rather than
creating a second reconciliation contract.

## Offboarding and retention

Termination is a reversible application-level soft state change, not deletion.
Retain the minimum account attributes needed for legal, learning-history,
reporting, and reconciliation obligations. Do not remove historical training
records or audit events as part of sync. Do not retain raw source files or raw
request payloads longer than the approved retention period; store hashes,
counts, stable identifiers, and redacted reason codes where possible.

Retention duration, legal hold behavior, and deletion/anonymization schedule
are deployment policy decisions (`ASSUMPTION`, not established by the current
staff-import migration). They must be configured before production activation.
Expired source artifacts may be cleaned up, while audit records remain
append-only for the configured audit retention period.

## Response and errors

The implemented event endpoint returns `200` with `event_id`, action, status,
external employee ID, internal employee ID when linked, changed field names,
redacted conflict details and a replay marker. It never returns the bearer
token, employee payload or unrelated personal data. Batch/dry-run response
shapes are not implemented.

Use stable machine-readable error codes:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` | Malformed body, unsupported mode, or invalid action |
| 401 | `UNAUTHENTICATED` | Missing, expired, revoked, or invalid token |
| 403 | `INSUFFICIENT_SCOPE` | Token lacks the required sync scope |
| 403 | `TENANT_SCOPE_MISMATCH` | Request attempts cross-tenant access |
| 409 | `event_id_reused` | Event ID exists with a different canonical payload |
| 200 | `status=conflict` plus an identity conflict code | Audited event was rejected without an employee mutation |
| 422 | `VALIDATION_FAILED` | Required field, value, or row validation failed |
| 500 | `SYNC_FAILED` | Internal failure; result must remain replay-safe |

An event-level conflict does not partially mutate the employee: employee work
runs in a nested transaction, while the redacted conflict event remains
auditable. Batch transaction semantics remain a future design gate.

## Audit requirements

Record an append-only audit event for request accepted, plan generated,
approval granted, commit started, each action outcome, and terminal result.
Each event contains tenant, session/request, integration identity, actor or
token subject, timestamp, mode, action/count summary, proposal revision/hash,
result/error code, and correlation/request ID. Store no token, password, raw
spreadsheet, or unnecessary personal data in event metadata.

The existing migration provides tenant-scoped `staff_import_session_events`,
ownership checks, RLS/force-RLS, and database protection against event update or
delete. These are repository-backed requirements to preserve when the sidecar
is implemented. The existing session states include review, approval,
committing, committed, rejected, expired, and failed; a sidecar status view
must map to those states or document a reviewed extension.

## Phased activation

1. **Contract and shadow mode:** issue tenant-bound tokens; accept only
   `dry_run`; compare plans with the existing staff-import preview; emit
   metrics and redacted audit events. No writes or provider calls.
2. **Pilot writes:** enable `ADD_OR_UPDATE` for explicitly allowlisted tenants
   and sources, with approval, low rate limits, rollback by reactivate/manual
   review, and reconciliation of counts against the canonical session result.
3. **Controlled offboarding:** enable explicit `terminate` and `reactivate`
   after retention policy, identity mapping, and incident runbook acceptance.
4. **Full reconciliation:** enable only after authoritative-export checks,
   absence/termination confirmation, stale-plan protection, audit review, and
   tenant-by-tenant rollback rehearsal are evidenced.

The local event slice is implemented but is not production-activated. Provider
database migration, tenant-isolation runtime tests, credential provisioning,
rate limiting and an operator acceptance rehearsal remain required. Batch and
full-reconciliation activation additionally require stale-proposal and
termination-count acceptance tests.

## Evidence and assumptions

- `GIT-DERIVED`: the repository contains tenant-scoped `staff_import_sessions`
  with a tenant/idempotency uniqueness constraint, explicit
  `ADD_OR_UPDATE`/`FULL_RECONCILIATION` modes, proposal revision/hash fields,
  approval fields, RLS/force-RLS, and append-only session events.
- `GIT-DERIVED`: the existing staff import parses CSV/XLS/XLSX, previews and
  commits create/update changes, matches by normalized tenant-local
  `personnel_number`, preserves omitted optional values, and uses
  `is_active`/`status` on users.
- `GIT-DERIVED`: `/v1/integrations/staff-sync/events`, tenant-bound hashed
  credentials, `external_employee_id` mapping, idempotent event hashes,
  `upsert`/`terminate`/`reactivate`, session revocation on termination, RLS and
  credential lookup are implemented locally with migration `0132`.
- `ASSUMPTION`: batch reconciliation, scheduled future events, invitation
  dispatch and retention durations remain proposed follow-up elements.
- `RUNTIME-DERIVED` (Supabase dev, 2026-08-26): migration `0132` applied from
  `0131` on PostgreSQL 17; all three Staff Sync tables have RLS and FORCE RLS,
  three tenant policies exist, and `PUBLIC` cannot execute the credential
  lookup function.
- `RUNTIME-DERIVED` (disposable synthetic contour): the actual FastAPI route
  passed upsert, replay, changed-payload rejection, update, audited email
  conflict, termination with refresh-session revocation, reactivation,
  two-tenant FORCE RLS isolation and credential revocation. Both staged runs
  finished with zero guarded-manifest residue and unchanged shared row counts.
- `PROVIDER-CONFIRMED` (Render dev, 2026-08-26): GitHub Actions run
  `32952220199` passed all six jobs for release
  `cf12ee260f0080ebcc4d70b440d4849bb70f8a10`; Render deploy
  `dep-da7b5bh42hec73atfgvg` reached `live` on the same release. Public health
  returned `app_environment=production` (production-grade behavior),
  `deployment_environment=render-development`, and the exact release SHA.
- `RUNTIME-DERIVED` (Render dev plus Supabase dev, 2026-08-26): the deployed
  route passed synthetic upsert, exact replay, update, terminate, reactivate,
  database readback, and revoked-credential rejection. The disposable tenant,
  employee, position, credential, identity and four events were removed; final
  guarded residue was zero.
- `NOT VERIFIED`: no production migration, real tenant credential, real
  employee data or external HR-system request was used.
