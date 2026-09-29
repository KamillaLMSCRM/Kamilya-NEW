# Module PRIVACY-CONTROL V1

| Field | Value |
|---|---|
| Status | Accepted |
| Template | V2 |
| Approved by | Kamilya owner, 2026-09-29 |
| Owning epic | PRIVACY-FOUNDATION-01 |

## Responsibility

Own the versioned mapping from a named processing operation and active role to
purpose, field names, data classes and `full/masked/deny` outcome.

## Non-responsibilities

RBAC authentication, tenant context establishment, data retrieval, masking
implementation, retention, provider routing and legal conclusions.

## External interface

```text
evaluate_processing(ProcessingRequest) -> ProcessingDecision
record_processing(db, tenant_id, actor_id, actor_role, operation,
                  resource_type, resource_id) -> ProcessingDecision
```

`record_processing` accepts only `full` in V1. `masked`, `deny`, unknown
operation and unauthorized role fail closed with `ProcessingDeniedError`.

## Data ownership and state

The module owns the code catalog and is otherwise stateless. It does not receive
personal values. Durable evidence is delegated only to Processing Ledger.

## Invariants

- Unknown operation is never allowed.
- Catalog metadata contains no customer or employee values.
- Policy version is included in every successful record.
- HR employees and system-team accounts use separate operation namespaces.

## Errors

`ProcessingDeniedError` is permanent for the request; callers must not retry
without a policy, role or adapter change.

## Security and privacy

Tenant and actor identifiers are server-owned inputs. Secrets, contacts, names,
document text and field values are forbidden in policy metadata.

## Verification and implementation packet

- Unit: `tests/unit/test_privacy_control.py`.
- Contract/integration: `tests/integration/test_privacy_processing_audit.py`.
- Read/write scope: `app/modules/privacy_control`, the three accepted adapters
  and their tests.
- Stop on a new operation family, response change, masking requirement or
  provider dependency.

## Definition of done

The pure policy, adapter integration, negative role and value-free ledger tests
pass; Graphify shows no dependency outside the accepted impact matrix.
