# Workbench neighbor catalog validation addendum V1

Status: Accepted by root for bounded LOCAL + read-only Supabase DEV validation,
2026-10-01, under owner's "го". Extends organization validation without changing
business rules or claiming a cloned schema equivalent to public. Product owner:
user; integration/writer: root; cheap inventory/reviewer read-only; Test Runner
owns frozen local acceptance. New business changes require another impact addendum.

## Interface, ownership and boundaries

Extend canonical workbench gate metadata-only mode with --catalog-details.
Inputs remain canonical env path and explicit --execute --metadata-only; supplying
details without metadata-only fails before dotenv/connection. No fixtures or DDL.
Read only the twelve named TABLES' pg_catalog metadata: complete policy USING and
WITH CHECK hashes/roles/command/permissiveness, ENABLE/FORCE flags, effective
lms_app table/column rights, outgoing FK names/targets/columns/deferral/actions,
table rights SELECT/INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER and column
rights SELECT/INSERT/UPDATE/REFERENCES (DELETE is not a column privilege),
user-trigger names/state/function identities and definition/body/search-path hashes.
No function invocation except canonical runtime identity check and catalog builtins.
No business rows, raw SQL/DDL/function bodies, token/email/audio/transcript output.
Definitions are hashed for source binding, not executed or saved as executable DDL.
Non-catalog dependencies/foreign targets are explicit unknowns, not silently cloned.

Output sanitized deterministic object inventory, foreign-table targets, per-table
isolation flags, legacy invitation exception and migration/runtime freshness
limitations. Collection success is not functional/tenant-equivalence PASS. Known
unsafe invitation exception blocks enablement; absent FORCE flags are named, not
silently corrected. Public migration0170 remains separately gated. Unknown function
or FK/trigger source blocks reconstruction/acceptance, not source-only investigation.

## Scope / negatives / verification

Read scope: exact catalog query plus source migrations/neighbor modules identified
by Graphify and source. Write: owned catalog script, minimal canonical gate wiring,
owned database-free tests and canonical plan/index/handoff/ledger. Application,
migration files, auth, public grants/policies, provider, workers, flags, QA stand,
source/retention policy and any public/business mutation are forbidden.
No arbitrary live DDL copying. Owned-schema reconstruction is NOT authorized by
this metadata-only addendum; it requires exact source-bound scope and readback.

Verify identity before catalogs, one READ ONLY transaction, table filter applied
to every query, no arbitrary function reads, no raw expressions/bodies emitted,
safe names/hash types, owner/runtime disposal on error, stable output ordering,
explicit NOT_VERIFIED equivalence and no fixture mutation. Actual read-only DEV
catalog proof, independent source review and frozen local Runner required.
No time-based scheduler or public migration follows. Rollback: remove local tooling;
no DB cleanup necessary. Stop on identity drift, unsafe output, unlisted module,
unexpected mutation need, or repeated access failure. Flags remain OFF.
Ready: existing-path preflight + one root writer + accepted scope. Done: bounded
metadata inventory and tests accepted with unresolved runtime/browser gates named;
not production GO. No user-visible contract/API or data owner changes.
