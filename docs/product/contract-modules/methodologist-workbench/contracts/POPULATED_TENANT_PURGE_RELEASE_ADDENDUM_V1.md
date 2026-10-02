# Populated tenant purge and release-head addendum V1

Status: Accepted by root,2026-10-02, BEFORE migration/controller implementation.
Extends staged compatibility and DEV activation V1; predecessors remain frozen.
Reason: actual DEV28 populated cleanup500/fk_enrollments_content_release_id and
fresh runtime ACL readback: all3 enrollment access/outbox tables deny DELETE.
Root owner/module owner: root. Product owner: human owner; existing instruction
to fix, finish, release and fully test the agreed slice. Independent reviewer:
bounded cheap source reviewer plus Test Runner. Approved by: root within that
repair scope; no customer deletion or new role/provider/billing authority.

## Responsibility, interface and invariants

Existing authenticated superadmin DELETE /admin/super/tenants/{id}?confirm_slug
remains the only application operation. It is permanent, exact-target and
non-repeatable (repeat absence404); protected kamilya slug cannot be deleted.
No ordinary methodologist/student/admin gains deletion permission. A new additive
0173 migration owns public.superadmin_purge_tenant_enrollment_access(uuid,text).
Only EXECUTE is granted to lms_app. Direct DELETE on credentials, delivery
policies and notification outbox stays denied; ENABLE/FORCE RLS stays unchanged.
The SECURITY DEFINER requires actual session lms_app or database owner, active
platform-superadmin context, exact matching app.tenant_id, existing target with
matching slug, and locks that tenant. Reject null/mismatch/protected target.
An active claimed notification blocks deletion; no notification dispatch.
Delete only exact target rows in those3 child tables, return bounded integer.
Revoke PUBLIC and known client/recovery roles. Function owner is the migration
database owner; explicit search_path=pg_catalog,public,pg_temp and qualified names.

Service order: reminder/approval purge -> bounded enrollment-access purge ->
quiz attempts/certificates/progress/enrollments -> immutable release purge ->
remaining existing tenant deletion. Keep transaction-local context and a single
successful commit; any failure rolls back. Existing FK/immutable guards remain.
Finite error500 tenant_delete_failed replaces raw database text; safe class-only
server diagnostics. No retention duration/scheduler/history edit otherwise.

## Release and compatibility

0173 adds an unused helper to compatible A26/DEV28 binaries. Never rewrite
already-applied0169-0172 or substitute ad-hoc public SQL. Canonical schema gate
head173 permits explicit expand169 and contract173 with the existing accepted
A26/schema169 compatibility receipt. Contract may start169,172 or173 only;
default mutation cannot bypass staged gate. Production B becomes exact169->173,
fresh169 backup/restore first; application rollback A26/OFF, not schema downgrade.
New helper downgrade only removes that helper/EXECUTE, not learning rows.

DEV controller adds schema kamilya-dev-release-v3 with the same strict activation
fields; its immutable schema receipt must be canonical PASS/current173/expected173.
LegacyV1/V2 keep original shapes and172 semantics; reject unknown/mixed receipts.
Candidate V3 is bound to the exact173 source and successful master CI before
prepare. Same3 existing Free/Hobby flags only, no new controller/resources.
Permanent QA verification gains explicit173; bootstrap remains168-only.
Native packetV2/build flag and host8-field manifest remain unchanged. Candidate
0.11.28 is not tagged/published yet; no previously immutable source is replaced.

## Verification and negative space

Read/write scope: new0173; superadmin service/router and owned tests; canonical
schema gate/DEV controller/QA verifier and their tests; existing epic index,
plan, release notes/readiness/error journal. Root owns all shared paths.
Independent test leaf owns only populated purge integration test.

Local ordering/rollback/error regressions, exact SQL ownership/ACL contracts,
empty/current upgrade and isolated canonical Supabase runtime proof required.
Prove same-tenant ordinary and superadmin wrong-tenant calls fail, protected and
wrong slug fail, active notification fail, runtime directDELETE remains denied;
authorized function removes only target children, rollback restores them.
CI real populated fixture: published release,2 enrollments, personal-link policy
and credential, unsent outbox, succeeded workbench plan; another tenant survives.
Correct owner-bound plan JSON and explicit readback contexts avoid RLS-hidden
false absence. Actual existing owned DEV A must purge via normal API then404;
B already404 is freshly checked. Permanent QA unchanged before/after. Preserve
original live pass and cleanup failures separately, no fixture rebootstrap.

Done only after exact new-source CI/DEV173/runtime/worker/live/readback/cleanup,
then protected production DB173/backend/native enabled identities and live flow.
Full arbitrary all-history tenant purge is NOT claimed: other modules' historical
RESTRICT/immutable dependencies need separately evidenced lifecycle coverage.
No voice/LLM/STT/mail, customer writes, broad prune, DNS/Proxmox, access expansion,
provider billing, new infrastructure or weakened tests. Stop at any scope drift,
role/owner/ACL mismatch, unknown head, failed restore/isolation/cleanup or CI gate.
