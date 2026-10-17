# Staff structure and safe transfers

Status: Accepted for DEV implementation, not accepted as delivered.
Version: V1. Template: V2. Decision date: 2026-10-17.
Product owner: human project owner; approved objective: integrate the reviewed
schema/roster in DEV and safely preview employee/unit transfers. Production excluded.
Root/module owner: Root. Independent reviewer: org_transfer_contract_review.
UI writer: assigned bounded frontend worker. Root approves technical interfaces;
business expansions, HR connector activation and production require the owner.
Change control: evidence -> independent review -> Root technical addendum; material
business changes return to product owner. Accepted versions remain immutable.

## Objective and journeys

A normal methodologist can navigate actual tenant structure and a server-paginated
employee roster, preview an employee's placement/position change or a unit's parent
change, inspect training and reporting-access consequences, and confirm exactly
that preview. Reload shows committed placement; repeated confirmation returns the
same receipt. Stale, expired, foreign-owner and cross-tenant plans cannot execute.

States: browsing -> selecting change -> ready preview -> succeeded receipt, or
rejected (invalid/stale/expired); no hidden retry or partial commit.
Journeys: company/unit/direct/subtree/unplaced navigation; employee transfer with
manual/completed learning retained; unit move affecting inherited training and
responsible-methodologist audiences; stale-preview rejection; idempotent retry;
cross-tenant/role denial; reload/back/error recovery; narrow-screen keyboard flow.

## Modules and interfaces

`Staff workspace -> organization read interface -> tenant structure/roster`

`Staff workspace -> change preview/confirm -> placement + training additions + receipt`

Reporting policy is consumed to calculate audience differences; roles, configured
responsibilities and authorization policy are NOT rewritten by transfers.

### READ V1

Responsibility: consistent effective placement (explicit user unit, else position
unit), account-active semantics, unit counts and bounded stable roster. Stateless.
No contacts, fabricated readiness/compliance or personnel-management status.
Interface: GET `/v1/organization-units/workspace?access=all|active|inactive` returns
`units:[{id,name,parent_id,unit_type,is_active,is_head_office,head_user_id,
breadcrumb,direct_count,subtree_count,hr_managed}],positions:[{id,name,department_id}],
total,unplaced_count`; GET `/v1/organization-units/employees` accepts `unit_id?`,
`unplaced=false`, `scope=direct|subtree`, `access=all|active|inactive`, `q?`,
`position_id?`, `missing_position=false`, `page=1`, `page_size=20` (max100), returns
`items:[{id,full_name,personnel_number,is_active,organization_unit_id,
effective_unit_id,placement_source,position_id,position_name,hr_managed}],total,page,page_size`.
No unit + no unplaced means company. Ordering: personnel number/null last then id.
Unknown unit/position is404; invalid combinations422; unavailable data is an error,
never a silently truncated complete population. Methodologist-only tenant reads.

### CHANGE V1

Responsibility: one server-owned preview/confirm contract hides change-impact policy,
concurrency and atomicity. Not a general employee-edit or HR synchronization interface.
POST `/v1/organization-units/changes/preview` body: `{kind:'employee'|'unit',
target_id,organization_unit_id:null|uuid,position_id?:uuid,reason:string}`.
For unit, organization_unit_id is the new parent; position_id must be absent.
For employee, position_id is required; null placement explicitly uses the existing
position fallback rule and must be labelled honestly in UI.
Response: `{id,expires_at,kind,target_id,from_path,to_path,affected_employees,
training:{added,no_longer_required,preserved_completed,preserved_other_sources},
reporting:[{user_id,full_name,before_count,after_count,gained,lost}],warnings:[string]}`.
POST `/changes/{id}/confirm` body `{confirmed:true}` returns `{plan_id,status:'succeeded',
affected_employees,added,preserved,executed_at}`. Confirmation must not accept a
replacement command, counts, fingerprint or client-supplied tenant/actor.

Owned data: tenant-scoped `organization_change_plans`, actor-owned read/insert/update,
RLS+FORCE RLS, tenant and user ownership validated. Root owns migration0182.
Preview expires15min; up to50 outstanding owned plans. Retention: ready plans may be
purged24h after expiry, succeeded receipts90days; cleanup must use owned maintenance
contract before DEV acceptance. No client DELETE. Names/contact data are not receipt
audit keys. Placement continues to belong to users/departments, not the UI.

Invariants: do not move/clone shared positions; do not change logins, account status,
roles, responsibility owners, completion evidence, course releases, manual/cohort/
program enrollments, PINs or notifications. Transfer training is deliberately
additive: add missing published effective courses for active students; retain every
existing enrollment unchanged, showing obsolete requirements as retained previous
assignments. Never relabel historical source provenance. No enrollment deletion.
Inactive users do not receive new automatic enrollments during transfer.

Concurrency: fresh SERIALIZABLE transaction on the existing pool, canonical tenant
and actor context; reload all impact inputs, compare fingerprint, lock plan; write
placement, additions and succeeded receipt atomically. No automatic retry after
serialization failure;409 requires fresh preview. A succeeded plan returns its
receipt before checking stale data or expiry. Identity/reason/commands are frozen.
Unknown impact or unsupported HR ownership fails closed. Structural cycles/depth8,
head-office root rule, duplicate siblings and active tenant ownership remain enforced.

Errors:404 absent/foreign resources;403 role denied;409 stale/expired/HR-managed/
serialization conflict,422 invalid command;503 disabled or unsafe snapshot size.
No partial update. Logs expose opaque IDs and error codes, not names/raw snapshots.

## Existing-module impact and negative space

| Owner | Class | Change | Preserved |
|---|---|---|---|
| organization_units | Interface | workspace/roster and guarded moves | canonical type-neutral roots, optional placement, legacy dedup |
| users | Consumer | placement written only by confirmed transfer | identity, contacts, roles, active/status, history |
| training rules/enrollments | Consumer | compute requirements, add missing only | all old rows and provenance |
| training_responsibility | Consumer | exact audience deltas | current authorization policy, heads, cohorts |
| staff import | Invariant | reject unreviewed changed existing placement/managed HR records in enabled contour | new/manual creation and unchanged rows |
| web staff | Interface | new workspace behind DEV opt-in | import, manual-add/edit, canonical routes |
| auth/provider/release | None | no policy, billing or production mutation | all existing limits and resources |

Legacy PATCH may rename but must not bypass preview for changed parent/head in the
enabled contour. Responsibility changes are a separate future reviewed command;
do not enable removing the last responsibility (which currently expands reporting).

## Future 1C personnel integration

Not a delivered connector. Future exchange needs immutable tenant+connector+entity+
external GUID identity (not name/email/personnel-number matching), effective dates,
versioned HR authority per field, idempotent upserts, no deletion on absence, separate
employment status and login access, conflict preview and protected manual exceptions.
Do not assume all imported/external_key records are HR-managed. Only explicit HR
source_metadata markers count; unknown/managed authority cannot be overwritten by
manual transfer/import. Current users have no connector namespace; connector work
requires its own accepted mapping/migration and must reuse this impact interface,
not execute direct placement updates or reactivate accounts during generic import.

## Verification, rollout and ownership

Pure policy tests precede implementation; then response/schema contracts, RLS and
cross-tenant/non-bypass integration in isolated canonical Supabase DEV, stale and
repeat/race transactions, existing organization/import/training regressions,
frontend tests/type/lint/build, real ordinary-role DEV browser/reload/mobile flow.
No local PostgreSQL. CodeGraph runtime and Graphify index absent in this checkout:
bounded source fallback; source/test/runtime evidence remains mandatory.
Root owns shared routes/contracts/migration, backend changes, staff-page integration,
documentation, DEV migration/deployment and final acceptance. Worker owns only the
new frontend workspace module/client/tests; independent reviewer owns no writes.
Stop on unknown module impact, authority, isolation, required-gate failure, HR
ambiguity or protected-history change; Root records disposition before resuming.

DEV opt-in only, existing Free/Free/Hobby resources; no production/master promotion.
Rollback disables new workspace and change routes; additive schema/receipts retained.
DoR: this interface/impact/ownership contract is frozen. DoD: all named gates passed,
exact DEV revision/readback, synthetic cleanup and docs updated; unverified gates
remain explicitly open and do not become success from tests alone.
