# Module PROCESSING-LEDGER V1

| Field | Value |
|---|---|
| Status | Accepted |
| Template | V2 |
| Approved by | Kamilya owner, 2026-09-29 |
| Owning epic | PRIVACY-FOUNDATION-01 |

## Responsibility

Persist one tenant-scoped append-only record containing the privacy policy
version, operation, purpose, outcome, reason, field names and data classes.

## Non-responsibilities

Business mutation ownership, payload storage, data export, legal retention
periods and tenant deletion orchestration.

## External interface

The module reuses `audit.log_action(...) -> AuditLog`; Privacy Control supplies
the namespaced action and value-free details.

## Data ownership

`audit_logs` remains owned by the audit module. `tenant_id` is mandatory; FORCE
RLS and tenant/superadmin policies remain unchanged. `lms_app` receives
`SELECT, INSERT` only after migration 0168. Bounded tenant purge remains owned by
the existing security-definer function.

## Invariants

- Ordinary runtime cannot update or delete a record.
- The processing record commits or rolls back with the business operation.
- No personal field value is stored in `details`.
- No second processing-event table or parallel source of truth is introduced.

## Error and concurrency behavior

Insert/flush failure fails the enclosing operation before its commit. Repeated
business commands may create repeated ledger rows; the ledger records events and
does not own business idempotency.

## Security and observability

Records are tenant-scoped and readable through existing authorized audit paths.
Action names begin with `privacy.processing.`; metadata is diagnostic but never
contains payload values.

## Verification and rollout

- Unit: `tests/unit/test_privacy_audit_migration_contract.py`.
- Integration: `tests/integration/test_privacy_processing_audit.py`.
- Migration: 0168, additive grant hardening; downgrade restores only UPDATE and
  intentionally does not restore DELETE.
- Release is a separate owner-authorized action; no deployment is implied.

## Definition of done

Migration contract, isolated PostgreSQL privilege check, tenant integration and
neighboring audit/RBAC regressions pass.
