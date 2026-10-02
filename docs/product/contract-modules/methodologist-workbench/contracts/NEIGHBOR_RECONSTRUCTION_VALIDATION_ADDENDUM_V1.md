# Source-bound assignment-neighbor reconstruction V1

Status: Accepted by root 2026-10-02 before implementation under owner's
"продолжай по плану. выведи в прод". Extends the read-only catalog addendum;
does not rewrite it. Product owner: user. Root owns integration, approvals,
shared source binding and actual DEV execution. Cheap leaf owns exact FK builder
and its database-free tests; independent reviewer/Test Runner own acceptance.

## Responsibility, interface and data ownership

Validation-only module. Prove the assembled bounded one-time assignment against
source-bound current DEV constraints/policies/triggers, then accepted0170/0172
changes in one random workbench_<12hex> schema. No new product behavior.
Input: canonical DEV owner/runtime URLs (process-local), explicit execution and
neighbor-profile opt-in, exact owned schema. Output: sanitized stage/check states,
counts and definition/source hashes, cleanup/public-metadata neutrality. Never
emit SQL, connection strings, business rows, credentials or contact data.
Fixtures are entirely synthetic; public metadata is read-only. Domain modules
remain data owners; only test tooling changes. State: preflight -> source-bound
baseline reconstructed/readback -> owned0170/0172 -> existing application gate
plus neighbor negatives -> exact cleanup. Failure blocks release, never bypassed.

## Impact and exact scope

Root writes scripts/ops/workbench_neighbor_reconstruction.py, minimal opt-in
integration in workbench_assignment_dev_gate.py, owned focused tests and canonical
plan/index/handoff/errors. Leaf writes only scripts/ops/workbench_neighbor_fk.py
and scripts/tests/test_workbench_neighbor_fk.py. Existing catalog/tooling is read
input, not changed except a strictly needed scoped adapter accepted by root.
Cheap ACL leaf owns workbench_neighbor_function_acl.py and its focused tests;
root integrates its read-only effective function ACL comparator. No shared writes.
No application/auth/worker/provider/migration changes under this addendum.

Twelve controls: tenants, users, user_roles, user_invitations, tenant_settings,
departments, positions, courses, content_releases, enrollments,
enrollment_access_policies, course_assignment_notification_outbox.
Referenced owned targets: documents, learning_path_assignments,
recurring_learning_assignments, learning_path_courses and learning_paths. The
last is a direct0056 SELECT-policy dependency of the0145 trigger's link-table
read. Clone definitions only, never public rows. Root amendment after the first
restored-controls run: reproduce source-bound SELECT policies, ENABLE/FORCE flags
and effective SELECT/column-SELECT rights on these five read-only targets. Revoke
all target mutations, do not install their write triggers or outgoing FKs, and
do not claim their write/lifecycle equivalence. A NULL recurrence reference does
not prove SQL planner privilege checks can never visit the trigger dependencies.
Source bindings: documents0042/0045/0126, learning_paths/link0056 plus exact purge
SELECT0126 where present, assignments0075, recurrence0098. Unknown policies block.
All27 outgoing FKs from twelve controls are reconstructed, no public FK pointers.
Root clarification before owned execution: two historical constraints have no
declaration in current migrations/models (0003/0035 also do not declare them).
Their trusted reconstruction declarations are accepted here explicitly:
departments_tenant_id_fkey: departments(tenant_id) -> tenants(id), ON UPDATE
NO ACTION, ON DELETE CASCADE; enrollments_course_id_fkey: enrollments(course_id)
-> courses(id), ON UPDATE NO ACTION, ON DELETE CASCADE. Both are validated,
NOT DEFERRABLE, INITIALLY IMMEDIATE. Bind these exact static declarations to this
contract and compare current catalog signatures; do not execute catalog DDL or
claim their original historical migration was located. Other25 retain their
concrete migration/model declarations. Any signature drift still blocks.
The referenced targets provide bounded constraint/read resolution, not a claim
of their own ingestion/recurrence/learning-path lifecycle acceptance. New command
creates only manual one-time assignments, never recurring/path/document mutations.
Those separate journeys remain unchanged and are not part of this feature GO.

Baseline26 policy identities/classes bind to latest local sources:
0013e legacy tenants service_access;0042 tenant policies;0044 platform lookup;
0045 platform sessions;0046 legacy invitation;0061 auth lookup;0081 content release;
0106 enrollment policy;0111 bounded lookup owner;0124/0126 exact purge;
0154 outbox owner;0161 organization isolation. Reproduce unsafe legacy policies
only in owned baseline, then replace using accepted0170/0172, never public.
No permissive substitutes. Actual migration/function owner role and membership
checked; do not grant a new role, BYPASSRLS or blanket app access.

Nine complete trigger definitions plus function body/language/config/security/
owner/ACL bind to source:0081,0106,0114,0127,0145,0161,0162. Dependencies include
0141 current privileged_tenant_purge_authorized (supersedes0123),0111 lookup_login_user_by_email and
0097/0154 already-reviewed enqueue. Do not install delivery/recovery functions,
invoke public functions or dispatch tasks. Only accepted local source SQL may be
executed after exact metadata/source binding. Do not copy arbitrary runtime DDL.
Rebase explicit public qualifiers and existing public search-path entries to the
owned schema; readback compares normalized PostgreSQL definitions, roles, events,
states, expressions and ACLs. Any unknown or drift stops before app fixtures.

## Invariants, errors and negative space

Actual lms_app non-super/non-bypass identity before security probes. Runtime tables
and every invoked project function resolve owned; public search-path fallback is
forbidden. Exact policy sets, ENABLE/FORCE flags, effective table/column rights,
27 FK targets/actions/validation/deferral and9 trigger events/configs compared.
Migrations0170/0172 are deliberate deltas, not preexisting equivalence. Existing
workbench0169/0171 and enqueue-only policies retain their accepted own proofs.
No privileged purge markers, scheduler/flag enablement, mail/OTP/AI/STT calls,
customer rows, QA reset or provider changes. Superadmin fixtures only in explicit
existing gates, never broad context for ordinary runtime assertions.
Unknown metadata/source, incompatible fixture, unexpected mutation or failed
cleanup -> BLOCKED with safe fingerprint. No raw driver errors. No source repair
of a neighboring business rule inside a test harness.

## Verification, ready and done

Ready: accepted scope, existing-path preflight, clean linked worktree, source map
for26 policies and9 bodies already located; Graphify stale/no matching current
catalog node, direct bounded source fallback. Exact source/definition mapping
must complete before owned app mutations, otherwise no acceptance.
Database-free builder/source/identifier/CLI/drift/output tests, scoped Ruff,
canonical quality. Actual DEV baseline readback, patched own/cross/empty negatives,
existing atomicity/concurrency/invitation/organization/retention application matrix
under restored neighbor controls. Add negative malformed foreign FK/reference,
immutable release and trigger ownership probes; preserve original fixture failures.
Drop exact schema and independently verify absence/public revision+table inventory
neutrality. Fresh review and frozen Test Runner required; runtime root evidence
is not independent Runner execution. No broad full-suite per edit.
Done: bounded assignment-neighbor fidelity/application gate accepted with these
exclusions explicit. Not whole-platform equivalence or release GO. No changed
roles, routes, queues, records, retention values or billing settings.

## Concurrency, rollout, rollback and stops

One root owner of external owned-schema mutations. No concurrent gate uses its
schema. Existing transaction/concurrency probes operate only synthetic rows.
This module is CLI-only, no API/scheduler, explicit opt-in defaults preserve the
older harness. Gate runtime uses existing Supabase DEV tier/limited NullPool,
never Docker PostgreSQL, new provider resources or spend.
Rollback is removal of local validation code and exact disposable schema cleanup;
no public changes. New target/callee/control, unexpected source mismatch, inability
to prove same scoped controls or drift in current public schema -> root contract
revision before resuming. Production authority is owner-confirmed but UNUSED;
all local/DEV/release/readback gates and exact staged compatibility remain required.
