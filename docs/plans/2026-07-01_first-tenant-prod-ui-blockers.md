# First Tenant Prod UI Blockers - 2026-07-01

## Scope

Make the product safe enough to launch the first real tenant in a semi-manual mode. This is not the full billing/superadmin epic. The goal is to remove confusing or dangerous UI paths and expose enough operational state for Askar/superadmin to manage the first tenant manually.

## P0 Findings

1. `/admin/team` allows selecting `superadmin`; backend `TEAM_ROLES` also allows tenant-scoped `superadmin`.
   - Risk: creates a platform role inside a tenant, contradicting the current model where platform superadmin has `tenant_id IS NULL`.
2. Superadmin tenant detail can create `teacher`, but `list_admins` only returns `admin`, `org_admin`, `superadmin`.
   - Risk: created methodologist disappears after refresh.
3. Superadmin UI does not show registration lead/contact data or trial usage counters.
   - Risk: first tenant cannot be managed without direct DB access.
4. Superadmin landing contains an internal API-card instead of launch operations.
   - Risk: the main operator surface is not useful during first tenant onboarding.

## Implementation Plan

1. Backend role safety.
   - Remove `superadmin` from tenant team-managed roles.
   - Keep platform superadmin access to endpoints as actor, but do not allow tenant users to be created/promoted to `superadmin`.
   - Include `teacher` in superadmin tenant admin/methodologist list and stats.

   Status: done.
   - `TEAM_ROLES` no longer includes `superadmin`.
   - `GRANTABLE_ROLES` remains `admin`, `org_admin`, `teacher`.
   - Superadmin tenant list/detail now counts and lists `teacher` as an operational tenant member.
   - Added `apps/api/tests/test_role_boundaries.py`.

2. Backend superadmin operational data.
   - Expose billing contact fields on `TenantResponse`.
   - Expose latest `tenant_leads` row for a tenant.
   - Expose `tenant_usage` counters for a tenant.

   Status: done.
   - `TenantResponse` now includes billing contact fields, `trial_started_at`, `usage`, and `latest_lead`.

3. Superadmin UI.
   - Tenant list: show contact email, trial date, usage summary, and clearer action labels.
   - Tenant detail: add "Launch control" block with contact/lead/usage/trial fields and quick manual actions.
   - Rename "Admins" UI copy toward "Admins and methodologists" where relevant.
   - Replace API debug card on `/admin/super` with first-tenant launch checklist.

   Status: done.
   - Tenant list now shows contact, trial status, usage and activity.
   - Tenant detail now has a `Launch control` block with lead/contact, trial usage and manual actions.
   - `/admin/super` debug API card replaced with first-tenant launch checklist.

4. Tenant admin team UI.
   - Remove `superadmin` role option.
   - Fix header layout and copy so it is clear this is system team, not learners/staff.
   - Add correct form names/autocomplete/focus-visible where touched.

   Status: done.
   - Removed `superadmin` option from `/admin/team`.
   - Header copy/layout now separates tenant team from learners/staff.
   - Existing create/edit flows now keep the page limited to `admin`, `org_admin`, and `teacher`.

## Verification

- Python compile for changed backend modules.
- Frontend typecheck.
- Next build if typecheck passes.
- Local grep confirms no `/admin/team` superadmin option.
- Production health check after push if backend changes are deployed.

## Remaining Launch Risks

1. Trial quota enforcement is still mostly policy-level unless every generation endpoint checks `tenant_usage`.
2. Email delivery telemetry is not surfaced in admin UI yet; for the first tenant, check Resend directly if an OTP/invite does not arrive.
3. Billing remains semi-manual: superadmin can switch plan/status/dates, but payment reconciliation is not automated.
