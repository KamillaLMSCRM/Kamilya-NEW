# Tenants bootstrap / RLS impact addendum V1

Status: Accepted by root 2026-10-01 before implementation. Approved by product
owner's explicit "да" to compatible tenants fix and conditional DEV0172 release.
Root owns auth/tenants/migration/gate integration; fresh cheap investigator and
bypass reviewer read-only; Test Runner independent frozen local acceptance;
Release Runner only exact accepted DEV packet. No production/billing authority.

## Responsibility / interface / ownership

Tenant data stays owned by tenants/platform modules; no retention/data migration.
Replace legacy0013e service_access ALL/PUBLIC true with own-ID runtime policy and
ENABLE/FORCE RLS, preserve0045 validated superadmin policy. Bootstrap lookup is
stateless: exact slug -> nullable UUID; exact tenant UUID -> login eligibility
boolean (not archived/suspended). No tenant objects/settings/billing returned.
Parameterized calls, fixed pg_catalog search_path, explicitly qualified table,
SECURITY DEFINER only for these read-only functions. Existing migration/function
owner receives SELECT policy like0111, never runtime blanket visibility or new
BYPASSRLS role. PUBLIC EXECUTE revoked, only lms_app granted; owner must differ
from lms_app/PUBLIC. Helpers operate only with empty tenant context and no
superadmin flag; authenticated sessions cannot enumerate foreign bootstrap IDs.
Current security boundary: server owns tenant/superadmin GUCs, not client input.
No claim to protect against arbitrary SQL execution as lms_app (existing context
setter already permits it); no API exploit/customer leakage asserted.

New-tenant creation allocates UUID server-side, sets transaction-local tenant
context BEFORE INSERT/flush. No public broad INSERT or arbitrary definer write.
Password domain resolution consumes UUID, not Tenant row pre-context; legacy
fallback keeps active-user/unambiguous semantics and eligibility filtering via
boolean function. Existing User auth_lookup behavior is not expanded to tenants.
Demo resolves bounded slug then own context; registrations retain email/legal/
OTP/slug collision behavior. Telegram existing user establishes context before
tenant payload; no bot API/security change. Invitation/kiosk established token
context, own-user payload, refresh/OTP, validated superadmin/impersonation preserve
their API/session/error semantics. Functions neither authenticate nor issue tokens.

## Impact / boundaries

Write scope root only: migration0172, tenants/bootstrap.py, auth/service.py,
auth/router.py demo resolution, auth/telegram_register.py and tenants/router.py
slug/creation wiring, auth/telegram.py context ordering, owned unit tests and
scripts/ops/tenants_rls_dev_gate.py; canonical index/plan/handoff/changelog/errors.
Read direct callers/models,0013e/0045/0061/0111/0170, exact focused neighbor tests.
Unchanged admin/superadmin CRUD keeps validated existing superadmin context;
invitations/kiosk/worker/domain operations remain consumers only. No roles/routes/
worker/task/session/OTP/registration policy/provider/AI/STT/mail/billing changes.
Do not change persistent QA or read customer business rows. No arbitrary live DDL.

## Verification / readiness / done

Ready: clean linked checkout/prewrite gate, graph+source investigation reconciled,
exact scope/approval above. Focused API helper/caller and migration contracts,
legitimate domain/legacy/duplicate/inactive password semantics; error propagation
and no new commits/side effects inside helper. Syntax/scoped Ruff and quality.
Actual canonical Supabase DEV in one random tenants_<12hex> owned schema: reproduce
legacy foreign read/update; apply accepted0172; non-super/non-bypass actual runtime
own CRUD, cross read/update/delete/insert denied, empty context denies table CRUD,
exact bootstrap outputs/alternate malicious slug class, own-context helper denial,
validated superadmin, owner-policy FORCE compatibility, function PUBLIC/runtime ACL,
same-connection rollback scope reset. Run actual app helper/password/new-tenant
seams on synthetic rows; source-only check is insufficient for them.
Empty/populated upgrade, no row rewrite, roll-forward downgrade. Drop exact owned
schema and independently read absence; public revision/table inventory neutral.
Full neighboring FK/trigger equivalence and browser acceptance remain separate.
Done local only after these gates plus fresh candidate review and frozen Runner;
DEV GO only after all preceding workbench isolation/release gates, exact readbacks.

## Rollout / rollback / stops

Functions expand FIRST, compatible API/worker SECOND, restrict tenants THIRD;
0172 full upgrade must not precede old API replacement. Need an exact staged DEV
release procedure that reconciles canonical schema gate; no ad hoc public DDL or
provider dispatch before accepting it. Functions-only installer belongs to0172
and never declares schema/release complete. Final repository head/readback required.
Rollback retains compatible helpers; do not restore broad service_access or disable
FORCE RLS.0172 downgrade refuses unsafe restoration. Flags remain OFF until full
acceptance; no scheduled cleanup. No bounded lookup output or secrets logged.
Stop on unnamed caller/module, unsafe function owner/DDL/metadata drift, public
resolution in owned gate, unexpected mutation, missing verification or expanded
external cost/authority; root revises accepted impact before resuming.
