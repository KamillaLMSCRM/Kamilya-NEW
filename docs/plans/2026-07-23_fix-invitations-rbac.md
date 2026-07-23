# Fix methodologist invitation RBAC

**Status:** completed and production-verified
**Date:** 2026-07-23
**Scope:** Restore the canonical methodologist workflow for listing and creating learner invitations without weakening tenant isolation or changing unrelated admin/training-log work.

## 1. Establish the actual authorization path and root cause

Inspect the invitation router, its role dependency, user/invitation services, frontend caller, and focused tests. Confirm the production `403` is caused by a role-policy mismatch rather than a tenant-context failure.

**What I found:** The invitation router already grants the active `methodologist` role access to list, create, and resend. The confirmed Demo tenant create `403` is intentional: `assert_can_send_invite()` raises `DemoLimitExceeded` for `Tenant.is_demo=true`. Listing does not call that guard, so its separate `403` must be identified from its response detail (role, expired/suspended trial, or tenant security context), not “fixed” by relaxing RBAC or demo limits.

**Status:** done

## 2. Add focused regression coverage before the correction

Cover methodologist list/create success, non-owning role denial, tenant-scoped resource non-disclosure (`404`), and expired/reused invite behavior where the existing invite flow owns it.

**What I did:** Added focused backend coverage for the methodologist guard, non-owner denial, non-demo create orchestration, tenant-isolated resend `404`, and expired-invite resend/supersede behavior.

**Verification:** `poetry run pytest tests/test_invitations_rbac.py tests/test_methodologist_role.py -q` passed (10 tests).

**Status:** done

## 3. Align invitation authorization with ADR-0012

Make the smallest backend (and only necessary frontend) correction so an active methodologist can perform employee/student invitation work within their tenant. Keep invite URL copying and expose actionable permission/server error messaging.

**What I did:** Kept the backend policy unchanged. The invitation page now hides the unusable creation form in a Demo tenant and explains the sandbox boundary; it also renders distinct permission and server-failure descriptions while retaining copyable URLs for successful invitations.

**Status:** done

## 4. Verify touched paths and record exact production smoke steps

Run focused backend tests, compile/type-check touched areas, inspect the final diff and working tree, then update this plan with outcomes and residual risks. No commit, push, deploy, or production-data changes.

**Integration verification:** backend `compileall` passed; the combined invitation and
training-log backend suite passed (24 tests); web `npm.cmd run typecheck` passed;
web `npm.cmd test -- --run` passed (10 files, 91 tests); Windows-compatible
`npx.cmd next build` passed; locale JSON parsing and repository-wide
`git diff --check` passed. The integration review also moved error classification
outside the component callback and prevented Demo tenants from making the history
request that had produced the confusing `403`.

**Production verification:** Vercel and Render deployed revision `5675f2b`.
In an authenticated Demo methodologist session, `/admin/invitations` rendered the
explicit sandbox explanation, no invitation-create control, an empty local history,
and no error notification. The non-Demo mutation path remains integration-tested.

**Remaining risk:** A non-Demo production methodologist account is not currently
available for destructive invite creation. Non-Demo behavior is therefore covered
by integration tests rather than a production write.

**Production smoke after deployment:** (1) sign in to an isolated non-Demo tenant as active `methodologist`; (2) open `/admin/invitations` and confirm `GET /api/v1/users/invitations?per_page=100` is `200`; (3) create a disposable student invite and copy its URL; (4) reload and confirm history contains it; (5) open URL in a clean browser context, accept it, and confirm the student session; (6) resend an expired invite and confirm the old URL is rejected while the new URL works; (7) use a second tenant methodologist against the first tenant invitation ID and confirm `404`.

**Status:** done
