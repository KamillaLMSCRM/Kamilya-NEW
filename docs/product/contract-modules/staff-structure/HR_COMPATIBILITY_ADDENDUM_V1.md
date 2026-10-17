# Optional HR / 1C compatibility

Status: Accepted design constraint for the current DEV packet, 2026-10-17.
Not an implemented or enabled 1C connector. EPIC_V1 remains immutable.
Owner request: some customers will want personnel integration; others must retain
the simple manual/import workflow. No production or external exchange is authorized.

## Current evidence and reuse

`staff_sync.models.StaffSyncIdentity` already separates tenant, source,
external_employee_id and internal user_id with unique source-specific bindings.
`StaffSyncEvent` records source/event_id, payload hash, action, effective_at and
outcome; `StaffSyncCredential` is tenant scoped. These are the employee identity
and event seams to extend, not replace with name/email matching or new User IDs.
Current source strings, effective timestamps and metadata are NOT by themselves a
complete connector/source-authority/version/conflict contract.

The new workspace reads effective placement and previews placement consequences;
it does not own the HR database. Explicit HR-owned units/positions and identity-linked
employees cannot be manually relocated in its enabled DEV contour. An arbitrary
external_key or imported spreadsheet does not imply HR authority.

## Intended authority matrix (connector implementation must enforce it)

| Data | Without HR integration | With explicitly configured HR authority |
|---|---|---|
| Legal company / branch / unit hierarchy | Manual or reviewed import | HR source; LMS read-only badge and conflict explanation |
| Employment/personnel identifiers, assignment, position, employment dates/status | Manual/import under existing rules | HR source; source-specific immutable identity and effective version |
| LMS login enabled/blocked and security roles | Existing authorized LMS role | LMS; never inferred from an HR text field or generic import |
| Responsible methodologist, cohorts, training rules, deadlines | LMS | LMS; HR changes cause a preview, not silent role edits |
| Courses, progress, attempts, completed learning and certificates | LMS | LMS; never reset or deleted on transfer/dismissal |
| Local exceptions/overrides | Ordinary reviewed edit | Explicit field-scoped override with author, reason, expiry and reconciliation policy |

Employment status and `User.is_active` are not synonyms. Future dismissal policy may
propose blocking access and stopping new automatic assignments, but requires an
explicit accepted lifecycle command. An absent row in a full/delta export never
means dismissal, account deletion or loss of history. Current admin access controls
remain LMS access controls; no new HR employment field has been delivered here.

## Identity, exchange and concurrency gates before activation

- Choose supported 1C product/configuration/version and exchange format from an
  actual customer export. Do not claim universal compatibility with “1C”.
- Bind credential -> tenant -> allowed source; source must not be arbitrary
  caller-selected authority. Separate independent employer/database namespaces.
- Extend source-specific immutable identities to units and positions before sync.
  Renames and personnel-number/email changes do not create duplicate people.
- Model a person, employment record, position catalog and staffing slot separately
  if the customer uses concurrent employments, substitutions or multiple companies.
  Current `User.position_id` / effective placement represents one primary assignment,
  not a delivered multi-employment HR model; do not silently flatten extra records.
- Validate effective_at and monotonic source version per entity. Exact event replay
  returns the original outcome; same event ID with a different hash is a conflict;
  older events cannot revert a newer placement or reactivate access.
- Exchange adapter submits a normalized placement command through the same impact
  policy/atomic writer as manual moves. No direct User/Department bypass. Additive
  training preservation, stale detection and receipt semantics remain mandatory.
- Stage bulk changes and show counts, conflicts, people/unit moves, course additions,
  retained learning and reporting-audience changes before authorized execution.
  Large batches need their own bounded per-item/batch transaction/recovery contract.
- Ownership enforcement must be independent of the DEV workspace feature flag.
  Audit all manual/import/admin/sync writers before connector activation; current
  DEV-gated guards are not sufficient evidence of production connector readiness.
- Monitor last successful exchange, rejected rows and out-of-order events without
  exposing credentials or payload PII. No public gateway, new paid resource or
  scheduled exchange is created by this addendum.

## Acceptance cases reserved for connector work

Rename preserving identity; same names in separate units/employers; personnel-number
change; transfer with completed/manual/cohort learning; reorganized unit subtree;
future-dated transfer and dismissal/return; absence in a partial export; multiple
employment rejection or explicit support; replay and conflicting replay; stale
version; manual override; transient retry; cross-tenant/source ID collision; preview
stale after HR update; generic import cannot clobber HR placement/status.

Current packet acceptance verifies only its conservative HR ownership guards and
the placement/preservation kernel. No connector capability may be advertised from
this design constraint or from dormant Staff Sync tables alone.
