# Multi-role team management UX

1. Reproduce the tenant-admin flow for adding an already assigned email, capture
   the exact 422 response, and map the frontend modal to the users/roles API and
   active-role switch flow with Graphify.
2. Add failing backend/frontend tests for the existing-account assignment path,
   stable modal layout, understandable role names/descriptions, and visible
   multi-role switching guidance.
3. Fix the smallest responsible backend/frontend surfaces without weakening
   tenant boundaries or the active-role authorization model.
4. Run focused and repository-level verification, update Graphify and the
   relevant user-facing documentation.
5. Push the tested revision, wait for green CI and production deployments, then
   repeat the tenant-admin add-role and active-role switch scenario in the
   browser.

## Step 1 — root-cause investigation

**Status:** complete

The modal detected an existing email but still posted the full form to
`POST /v1/users`. Empty hidden profile/password fields produced a schema-level
422 before the API's existing-account fallback could assign the role. The form
also conditionally removed three fields, causing the unexplained layout jump.
Graphify selected the team page, users router/service, auth role-switch route,
auth store, TopBar, and role policy for focused inspection.

## Step 2 — regression tests

**Status:** complete

Added backend schema regression coverage, pure frontend request-shaping tests,
localized role-copy assertions, and a rendered modal scenario that verifies
stable fields, the existing-account role endpoint, and immediate auth-state
refresh when the current user assigns a role to their own account.

## Step 3 — implementation

**Status:** complete

The frontend now uses `POST /users/{id}/roles` for a matched account, keeps
profile/password fields visible but disabled, explains each role and the
top-bar working-mode switch, and prevents duplicate-role submissions. The API
normalizes an empty compatibility password to missing while retaining the
eight-character requirement for new accounts.

## Step 4 — local verification

**Status:** complete

Verified 39 backend unit tests, 100 frontend tests, frontend typecheck, lint,
and a production Next.js build. Database-backed backend integration tests could
not start because the local PostgreSQL test endpoint refused the connection;
the failure was captured separately from code regressions. User documentation
was updated, and Graphify was refreshed in code-only mode.

## Step 5 — production verification

**Status:** in progress

The first production pass confirmed the fixed stable modal and successful
methodologist assignment without a 422. It also exposed that a self-assignment
did not refresh the current browser's assigned-role list until session refresh.
The follow-up updates auth state from the successful assignment response so the
top-bar working-mode selector appears immediately.
