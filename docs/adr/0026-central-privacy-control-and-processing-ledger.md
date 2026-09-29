# ADR-0026: Central privacy control and processing ledger

- Status: Accepted
- Date: 2026-09-29
- Approved by: Kamilya owner

## Context

Kamilya already has tenant-scoped audit records and route-level RBAC, but data
processing decisions were implicit in individual endpoints. Employee and
training-result exports did not emit one structured, machine-readable record of
which categories were processed and for what purpose. Historical grants also
left `UPDATE` available on `audit_logs`, although ordinary runtime records are
intended to be immutable.

## Decision

1. `privacy_control.evaluate_processing()` is the sole catalog decision seam.
   Unknown operations and roles fail closed.
2. Operation policy contains only field names, data classes, purpose, roles and
   outcome (`full`, `masked`, `deny`). It never receives or stores field values.
3. `privacy_control.record_processing()` accepts only a `full` decision in V1,
   then appends policy metadata to the existing `audit_logs` ledger in the same
   transaction as the successful business operation.
4. `masked` also fails closed until a versioned adapter contract defines the
   actual masked representation.
5. `audit_logs` remains the ledger owner. Runtime `lms_app` may read and insert,
   but migration 0168 revokes `UPDATE` and `DELETE`. The bounded tenant-purge
   function from migrations 0148/0149 remains the only deletion path.
6. HR employees (`employee.*`) and tenant system-team accounts
   (`team_member.*`) are separate operations even though both persist in
   `users`.
7. An authorized tenant business workflow normally receives the full values it
   needs. Missing authorization is handled by omission or denial, not by using
   masking as a substitute for RBAC, RLS or reporting scope. `masked` is used
   only for a separately catalogued disclosure surface where partial value
   recognition is necessary and full disclosure is not.
8. The reviewed logical flow inventory is maintained in
   `docs/legal/kamilya-personal-data-flow-map-ru.md`. Adding a new external,
   public, diagnostic, export or cross-environment disclosure path requires an
   update to that map and to the implementation register.

## Consequences

- Policy drift is testable through one pure interface.
- The ledger is useful for later compliance reporting without duplicating a
  second event table.
- Existing RBAC, response bodies and UI do not change in this foundation step.
- Blanket masking of tenant UI and authorized internal exports is explicitly
  not a consequence of this ADR.
- No public claim, provider configuration, infrastructure routing or customer
  instruction is part of this decision.
