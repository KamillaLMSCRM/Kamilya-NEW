# Workbench retention implementation addendum V1

Status: Accepted for LOCAL + owned synthetic DEV implementation, 2026-10-01.
Approved by: root integration owner under owner's approved RETENTION_POLICY_V1
and explicit "делай". Public migration/deletion/scheduling remains unapproved.
Reason: implement approved durations without changing learning history or roles.
Changes require a new version accepted by root; scope/duration changes by owner.

## Responsibility and interface

Workbench owns only assignment plan/snapshot/preview/receipt metadata. Migration
0171 adds nullable executed_at, a DB-owned timestamp trigger and one bounded
SECURITY INVOKER function cleanup_workbench_assignment_plans(integer,boolean).
No API route, worker, scheduler, tenant enumeration or deployment is added.
Module owner/writer/migration owner: root. Reviewer: independent cheap reviewer
and Test & Evidence Runner on a frozen local candidate.

- Inputs: trusted transaction-local app.tenant_id and app.is_superadmin=true,
  actual current_user=lms_app; batch limit1..500 (default100); apply boolean
  (defaultfalse/dry-run). No caller-supplied time, tenant IDs or arbitrary predicate.
- Output: selected/deleted plan ID and status only; no snapshots/PII. Caller owns
  commit/rollback. Invalid inputs/context fail before selecting/deleting rows.
- Dry-run locks no records and changes no data. Apply locks eligible rows with
  FOR UPDATE SKIP LOCKED, deletes at most the limit, deterministic oldest-first
  selection (eligibility timestamp then ID). Locked candidates can be skipped;
  exhaustion is not a claim that concurrent work finished. Retry is safe.
- Ready eligibility: expires_at <= transaction_timestamp()-24hours.
- Succeeded eligibility: executed_at IS NOT NULL and
  executed_at <= transaction_timestamp()-90days. Future times remain protected.
- Existing succeeded rows without trustworthy time remain NULL and are skipped.
  No created_at backfill, guessed receipt time or silent historic deletion.

## State, persistence and authorization

New inserts start ready with no execution timestamp. The existing atomic
ready -> succeeded update stamps clock_timestamp() in a BEFORE trigger. Rollback
rolls it back with receipt/enrollment/outbox. Succeeded status/receipt/timestamp
are immutable; replay returns the same receipt without updating its retention.
No UPDATE grant for executed_at; ordinary methodologists cannot stamp/backdate.
Existing SELECT/INSERT/limited UPDATE and exact-tenant superadmin purge policy
remain; no new DELETE grant/policy/bypass/role/SECURITY DEFINER. Function EXECUTE
is revoked from PUBLIC and existing non-runtime roles, granted only to lms_app.
Explicit tenant predicate AND existing FORCE RLS constrain both maintenance
preview and deletion, including superadmin context. No foreign-tenant locator
input exists. Missing tenant or ordinary actor context raises insufficient_privilege.

Deletion removes only workbench metadata; no downstream domain rows are owned
or cascaded by it. GET/confirm of removed ID remains plan_not_found; no plan
reconstruction, enrollment retry, invitation creation or notification redispatch.
Concurrent receipt replay either reads its locked record before deletion or sees
not found after deletion, never executes a previously succeeded command.

## Impact, scope and negative space

| Module | Impact | Required protection |
|---|---|---|
| Workbench model/DB | Interface addition | migration/trigger/ACL/retention boundaries |
| Workbench confirmation | Existing consumer | same atomic update, replay timestamp stable |
| Owned DEV gate | Verification extension | 0169+0171 only in random owned schema |
| Enrollments/access/outbox/course/user/invitation | None | before/after domain identity/count equality |
| Auth/invitation0170/tenant purge/UI/providers/workers | None | no source/config/policy changes |

Read scope: named workbench source/tests, migrations0169/0171, existing owned DEV
gate and relevant canonical instructions/environment/error records. Write scope:
0171, assignment_models.py, retention-owned tests/gate helper, minimal existing
gate wiring and canonical plan/index/handoff/backlog/changelog. No new dependency.
No public DB/business data/OTP/mail/AI/STT/browser mutations.

## Verification, observability and completion

Database-free contracts plus actual canonical Supabase DEV under non-super,
non-BYPASSRLS lms_app: migration over empty and pre-existing ready/succeeded rows;
NULL legacy preservation; boundary clocks; ordinary/no-context denial; exact-tenant
maintenance only; timestamp ACL/trigger immutability; rollback/replay; dry-run;
batch cap/ordering/idempotence; removed GET/confirm no effects; locked candidate
skip and concurrent cleanup/replay outcome. Existing assignment DEV gate and
impacted local tests run once on integrated delta. Preserve sanitized failure
classes/check names, not SQL, DSNs, snapshots or PII. Root reviews exact diff,
independent findings and frozen Runner result before local acceptance.

Definition of Ready: approved durations, explicit local scope, canonical DEV
path and prewrite guard, contract and one writer. Definition of Done: tests and
actual isolated gate PASS, owned schema absent/public metadata neutral, independent
review accepted, local commit; not production GO. Stop on unexpected dependency,
role/bypass or public mutation need, isolation/cleanup failure, repeated access
failure, or test weakening. Disable flags remain OFF. Rollback retains additive
schema/time evidence;0171 downgrade refuses erasing timestamps (roll forward).
Old API remains compatible because its status update triggers the timestamp.
Scheduling/public migration requires separate exact rollout authority.
