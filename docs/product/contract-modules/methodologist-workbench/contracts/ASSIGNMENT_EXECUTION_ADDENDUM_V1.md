# Assignment execution addendum V1

Accepted by root for bounded local implementation, 2026-10-01, under owner's
"ок. делай". Extends EPIC/WORKBENCH/COMMAND-PLAN V1 without replacing them.
Production enablement, audio/providers/spend and public DEV migration remain gated.
Root owns integration/models/migration/router/docs. Cheap leaf writers own only
the parser+tests or frontend panel+tests named in their packets. Reviewer independent.

## First slice / compatibility

One-time assignment of an existing published native/SCORM course to an existing
active department. No draft creation/publication/rules. Local bounded text parser
accepts only `Назначь курс "TITLE" отделу "NAME" до DD.MM.YYYY` (also ISO date,
Russian guillemets). It does not call LLM and is not a general natural-language
understanding claim. Unsupported/negative/compound/relative-date commands return
clarification, never a guessed action. Explicit context fields timezone_name,
notify and include_descendants are shown next to the instruction. Default notify
false, include_descendants false. No silent expansion to descendant departments.

API behind METHODOLOGIST_WORKBENCH_ENABLED=false, methodologist active role only;
frontend behind NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED. Routes:

- POST `/methodologist-workbench/assignment-preview`: instruction (1..4000),
  timezone_name (IANA), notify bool, include_descendants bool; optional course_id/
  department_id only for choosing server-returned ambiguous exact-name matches.
- GET `/methodologist-workbench/plans/{plan_id}`: owned preview/receipt reload.
- POST `/methodologist-workbench/plans/{plan_id}/confirm`: existing
  ConfirmationRequest only; plan_id in body must equal path.

Preview response discriminated by state `clarification_needed` (code plus known
tenant-local `{id,label}` course/department choices), or `preview_ready`:
plan_id, revision, fingerprint, expires_at, course_id/title/release_id,
department_id/name, timezone_name, due_at, notify, include_descendants,
recipients `{user_id,label,already_assigned,access_warning}` (max5000),
new_count, skipped_count. IDs are not tenant authority; selected IDs must match
the parsed exact-name candidates. Receipt state `succeeded`: plan_id, created
`{user_id,enrollment_id,notification_id}` and skipped user IDs, notification state
`queued` or `not_requested` (NEVER delivered). Cache-Control no-store.

## Resolution and snapshots

Exact trimmed/case-insensitive names, no fuzzy auto-selection/creation. Missing
or ambiguous names → clarification. Deadline becomes 23:59:59 of the explicit
date in displayed IANA timezone; reject past, invalid, relative or ambiguous
dates. No existing tenant-timezone setting is assumed; context is explicit.

Canonical placement: explicit User.organization_unit_id wins; otherwise owned
Position.department_id. Students only, is_active=true AND status=active. Default
direct department; descendants only if explicit true using existing scope resolver.
Preview does not create a ContentRelease: legacy published courses without a
valid current release must use existing owner workflow first, returning conflict.

Source of truth is persisted immutable JSON PlanSnapshot plus server metadata,
not submitted client/model plan. Audience token hashes exact scope options,
timezone, course/department labels, active member IDs, placement/access metadata
and existing non-recurring enrolled/in_progress/completed IDs. Course reference
token binds immutable current release ID. Existing assignments are shown/skipped,
their deadlines/history never rewritten; recurring occurrences remain independent.
No credentials/learner contact details/raw instruction in persisted snapshot.

## Persistence / transaction / replay

Migration0169 adds workbench_assignment_plans: id, tenant_id, actor_id, immutable
snapshot/metadata/fingerprint, created_at/expires_at, status ready|succeeded,
receipt. Tenant FK cascade; actor ownership enforced by RLS checks. ENABLE/FORCE
RLS, lms_app no BYPASSRLS; tenant+app.user_id policy; INSERT verifies active
methodologist owner in same tenant, restricted column UPDATE status/receipt only.
No runtime DELETE except exact superadmin purge policy. Canonical purge list
deletes this table before users. No unrelated generic purge repair in this scope.
Downgrade refuses a nonempty table: disable feature, don't destroy receipts.
Metadata retention is not approved for production until scheduled retention
contract is accepted; feature remains off pending that gate.

Confirm locks owned plan row; matching succeeded request returns stored receipt
without domain mutation, even after preview expiry. Wrong fingerprint/revision
still rejects. For ready plan, lock course and active department, re-read/lock
tenant positions and candidate users in deterministic UUID order, re-resolve scope
and existing enrollments, reconstruct authoritative snapshot and compare. This
defines one-time audience at the guarded re-read; subsequent new hires are not
automatically assigned. Predicate insertion/cross-operation races require DEV
tests before enablement; locks alone aren't claimed phantom protection.

Use existing transaction-compatible enroll_users: due_at explicit, delivery_mode
email; assigned_by=actor only if notify=true, otherwise None (no invitation/outbox).
Check returned recipients equal expected new set; mismatch rolls back entire
transaction, not silent partial success. Persist receipt in same transaction;
commit before optional Celery dispatch. On integrity/deadlock errors rollback and
return conflict, never retry with a different audience. Existing outbox recovery
timer remains owner of queued messages. No claim of delivered notification.

## Impact / negative space / verification

New module, migration, owned tests and frontend surface; existing changes limited
to config flag, main router registration, model registry and one purge list entry.
Enrollment implementation/old routes, organization rules, course publish/review,
AI, billing, auth, providers and customer data unchanged. Source/contracts/UI
tests plus canonical quality checks, isolated Supabase migration/ACL/RLS, then
application transaction/concurrency and browser DEV required. Unverified DB/UI
checks are named gaps, not substituted by mocked tests. Feature flags remain off
until all corresponding gates pass. Unexpected imports or neighboring writes →
stop and version addendum. Rollback disables flags; no data erasure.
