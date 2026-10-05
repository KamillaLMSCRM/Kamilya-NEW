# WB-LESSON-CORRECTION-APPLICATION-DEV V1

Status: Accepted root-owned validation impact, 2026-10-05. Owner continuation
"делай" accepts the isolated application gate described in the preceding handoff.
Preserves APPLICATION V1/V1.1, PREVIEW V1..V1.4 and existing preview validation.

Root owns new scripts/ops/workbench_correction_application_dev_gate.py,
workbench_correction_application_dev_checks.py, their scripts/tests regression,
execution and plan/index/journal. Existing preview/document helper interfaces and
application owners remain unchanged. Review is independent, source/local only.

## Exact target and authority

Canonical Supabase DEV owner/runtime URLs from primary Kamilya-NEW/.env, verified
same project/database and non-super/non-BYPASS lms_app. No new provider resource,
paid call, account login, file upload, email, queue or billing change. Internally
generate one workbench_<12hex> schema; reject collision and unsafe name before
ownership. Commit creation, qualify all owner writes, rebind runtime search_path
to exactly owned schema/pg_catalog on every transaction including service commits.
At most three simultaneous connections. Always cleanup owned schema; prove absence
on a fresh connection and unchanged public revision/table inventory. Never drop
a preexisting schema; no public data/schema writes or grants on global objects.

## Actual FK boundary, not structure-only evidence

Reuse structure-only preview neighbors. Add exact application neighbors:
course_approval_requests, workflow_work_items, workflow_access_credentials,
audit_logs, course_content_releases, course_content_release_items. Additional
learner history neighbors may be named in a successor contract before writes.
No public rows copied. Recreate public catalog-bound FK definitions whose source
and target are both in this allowlist, strictly rebinding REFERENCES to owned
schema. Refuse unsafe definitions, external schema targets for required edges,
unvalidated or deferred required FKs. Prove required course/module/lesson/block/
quiz/question/choice/SCORM and approval hierarchy edges and exact recreated
catalog definitions; omitted external optional edges are explicitly NOT VERIFIED.
Synthetic neighbor RLS remains a fixture, not public policy/trigger equivalence.
Apply real0176 and0177 with existing Alembic Operations schema seam.

## Agreed service and SQL seams

Two synthetic tenants and owned/sibling/foreign ordinary methodologists. Actual
original-MD converter, evidence, quality, resolver, preview, application, lesson,
approval, audit and receipt services. Stub external storage bytes/configured model
response only; no internal owner mocks. Seed reviewed draft plus assessment and
approval artifacts, preserving original immutable snapshots. Real-provider quality,
UI/auth and whole public neighbor equivalence remain separate gates.

Required vertical checks: apply/read/replay, concurrent same-plan one application
audit/receipt, changed seal/context and published refusal, role loss/foreign/sibling
and absent-context reads/writes, DB ACL/FORCE-RLS/immutable receipt and forged insert
refusal; one transaction rollback on actual DB audit/receipt faults; committed
receipt survives lost acknowledgment (transport boundary injection only). Direct
writer and approval owner contention use actual services where feasible; bind
claims to each observed case, never extrapolate all writers. Prove immediate FK
insert/move contention with real sessions and explicit lock readiness, bounded
timeouts and no wall-time-only concurrency claim. Failed checks stop acceptance.
Receipt downgrade refuses populated table; empty downgrade/re-upgrade works.
Checks are unique/complete and sanitized; SQL failures expose only class/SQLSTATE/
safe source location. Preserve every failed receipt, never relax existing guards.

PASS is isolated application runtime only, never production or end-user feature
GO. Retention/reconciliation, real model semantics, learner history fixture,
before/after UI, assembled DEV and exact release/production smoke still gate launch.
