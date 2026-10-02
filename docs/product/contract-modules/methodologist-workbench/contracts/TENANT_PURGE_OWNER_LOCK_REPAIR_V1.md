# Tenant purge owner lock repair V1

Accepted root design2026-10-02 within the owner's fix/finish/production scope;
extends POPULATED_TENANT_PURGE_RELEASE_ADDENDUM_V1 without replacing it.
Root owns migration, integration, final docs and external changes. Cheap leaf
source review corrected its initial SELECT-only hypothesis against official
PostgreSQL17 semantics and accepted the UPDATE-policy design.

Confirmed production173: exact synthetic B present/right slug; both lms_app and
kamilya_migrator SELECT visible1; non-bypass owner FOR UPDATE EXPLAIN false,
runtime FOR UPDATE not false. First reminder helper raises tenant-confirmation
rejection; service transaction preserves both synthetic tenants. Evidence:
managed workbench28-production-cleanup-owner-lock-root.json eeadaf11e392e13845ef4910d8dc12f04e7697181fe3edb73808fcb27fd417f1.

0174 adds tenants_purge_function_owner_lock FOR UPDATE TO actual database owner.
USING: current_user exact owner; session_user lms_app/database owner; active
superadmin; exact transaction-local tenant ID; slug not kamilya. WITH CHECK(false).
Existing SELECT owner policy supplies read visibility; this policy supplies
lock visibility only. No grants, role attributes/memberships, RLS mode, business
rows, function bodies or public routes change. Downgrade drops only this policy.

Public DEV gate174 requires repair from173/174 only; no default apply or older
staged-contour shortcut. Provider flags stay ON; ordinary existing-resource DEV
deployment follows independently verified174 receipt. Production protected
173->174 with exact source/image/CI and backup/restore; rollback app28 on174,
not schema downgrade. Retain native28 exact64/ON; no CT137 build/cleanup needed.

Acceptance: actual non-bypass row-lock regression under owned transaction-only
schema/NOLOGIN role, ordinary/foreign/empty/protected negatives, real UPDATE and
INSERT denied, DELETE zero, original rows intact, policy downgrade/reapply;
fresh owned schema/role absence and unchanged public catalog. Use existing
canonical temporary-owner procedure; never grant SET/CREATE/BYPASS to shared roles.
Then exact-source CI including populated API cleanup; actual production normal
API deletion of the already owned A/B only, fresh404 plus independent absence;
retained QA completion/history/certificate unchanged. Full arbitrary historical
tenant cleanup is not claimed. Test Runner owns independent local regression;
Release Runner owns immutable packet review, root resolves executor access.
