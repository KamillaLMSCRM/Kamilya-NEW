# Trial Enforcement Report

**Date:** 2026-07-14  
**Status:** implemented and unit-tested

## Policy

- Login remains available after a trial expires so the tenant can see the upgrade/support surface.
- Tenant operations protected by `require_role` are blocked with HTTP `403` and machine-readable code `trial_expired`.
- An active `paid_until` period overrides an expired trial date.
- Suspended and archived tenants receive `tenant_unavailable`.
- A platform superadmin without a tenant context is not blocked by tenant billing policy.
- Impersonation keeps the target tenant context, so an expired target tenant is blocked unless an explicit platform flow uses a superadmin endpoint.

## Implementation

`get_current_active_user` now calls `assert_tenant_access`. `require_role` depends on that function, so the policy applies consistently to role-gated tenant operations including course authoring, AI generation, quiz editing, assignments, staff operations, cohorts, integrations, certificates settings, and other protected mutations.

`require_tenant_user` keeps its separate tenant-context check for tenant-scoped routes and no longer performs the policy query twice.

## Verification

Covered by `apps/api/tests/test_trial_and_ai_dispatch.py`:

- active trial;
- expired trial;
- paid period overriding expiry;
- suspended tenant;
- role-gated mutation path rejecting expired trial;
- superadmin without tenant context bypassing tenant policy.

Targeted result: **11 passed**.

## Remaining product work

The frontend should surface `trial_expired` as a dedicated upgrade/support state instead of a generic error. Billing checkout and paid-plan provisioning remain separate product work.

