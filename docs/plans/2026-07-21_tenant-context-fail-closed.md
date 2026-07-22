# Tenant context fail-closed hardening

**Date:** 2026-07-21
**Scope:** FastAPI authentication dependency, tenant RLS context, and regression coverage.
**Constraints:** no production DB/DNS/deploy changes, no migration, no commit or push.

## Plan

1. Reproduce and document the transaction state after `SELECT set_current_tenant(...)` fails, including whether subsequent ORM access is possible without rollback.
2. Add focused regression tests for failed tenant context, normal tenant authentication, platform superadmin, impersonation, and cross-tenant resource hiding.
3. Implement the smallest fail-closed change in the authentication dependency and remove the false ORM-fallback claim without weakening production RLS.
4. Run targeted auth/RBAC/tenant tests, then the full backend suite when the local PostgreSQL/pgvector environment is available; inspect the final diff and working tree.

## Step reports

Reports are added immediately after each completed step.

### Step 1 — investigate failed tenant-context transaction behavio

**What I found:** `get_current_user` catches any exception from `SELECT set_current_tenant(:tid)` and then continues to the user ORM query. There is no centralized ORM tenant filter in `app/core/db.py`, so the documented fallback is false and the control flow is fail-open by design even if PostgreSQL often prevents the next query incidentally.

**Transaction evidence:** against the local development PostgreSQL, a deliberately missing tenant-context function raised `ProgrammingError`. The `AsyncSession` remained inside a transaction; `SELECT 1` before rollback raised `DBAPIError`, and `SELECT 1` succeeded after `session.rollback()`. Therefore a database statement error normally aborts PostgreSQL transaction work, but application security must not depend on that backend-specific side effect or on the current connection role.

**Canonical contract:** `AGENTS.md` requires every data-access path to use tenant isolation and mandates `404`, not `403`, for cross-tenant resource hiding. The weak enrollment test currently permits `200`, while the service does not first prove that the requested course belongs to the caller tenant.

**Checks:** repository search for all `set_current_tenant` call sites; focused inspection of `core/auth.py`, `core/db.py`, impersonation token creation, enrollment router/service, and tenant-isolation tests; read-only local PostgreSQL transaction probe.

**Status:** done.

### Step 2 — add regression tests before the fix

**What I changed:** added `tests/test_auth_tenant_context.py` with dependency-level and ASGI-level coverage for tenant-context failure, normal tenant authentication, platform superadmin context, and tenant-scoped impersonation. Corrected the enrollment cross-tenant test to call the real `/api/v1/courses/{course_id}/enrollments` route as a methodologist and require the canonical `404` response.

**RED evidence:** `pytest tests/test_auth_tenant_context.py -q -p no:cacheprovider` produced `3 failed, 2 passed`. The failures prove that the current code continues after the tenant-context exception, returns an unhandled error instead of a controlled `503`, and enables `app.is_superadmin` during impersonation.

**Status:** done.

### Step 3 — implement fail-closed security context handling

**What I changed:** `app/core/auth.py` now establishes tenant RLS context through one fail-closed helper. Any error is logged without continuing to ORM access, the failed transaction is explicitly rolled back, and the request receives a controlled `503 Tenant security context unavailable`. The false centralized ORM-fallback comment was removed.

**Superadmin/impersonation:** genuine platform-superadmin requests still enable `app.is_superadmin` after the user is loaded. Impersonation now validates the platform identity and matching target tenant, returns the tenant-scoped wrapper, and does not enable the global superadmin RLS policy.

**Cross-tenant enrollment:** enrollment listing now first proves that the course exists in the caller tenant and maps absence to `404`, matching the canonical resource-hiding rule.

**GREEN evidence:** `pytest tests/test_auth_tenant_context.py -q -p no:cacheprovider` passed `5/5`. The corrected enrollment cross-tenant integration test passed against the local development PostgreSQL.

**Status:** done.

### Step 4 — verification and final scope review

**Graphify:** installed the documented CLI, built a code-only graph, and queried the auth-to-database and enrollment isolation paths. It selected `app/core/auth.py`, `app/core/db.py`, `app/modules/enrollments/router.py`, `app/modules/enrollments/service.py`, `tests/test_auth_tenant_context.py`, and `tests/test_tenant_isolation.py`. The graph was refreshed after the final test correction; `graphify-out/` remains untracked.

**Targeted checks:** the combined auth/RBAC/tenant run passed `49 tests`; the focused tenant-context file passed `5 tests`; the corrected cross-tenant enrollment integration test passed against the local development PostgreSQL.

**Full verification:** `pytest tests -q -p no:cacheprovider` passed `379 tests` in the local development environment. `python -m compileall -q app tests` passed. Ruff check and format check passed for the new focused test; existing touched modules retain unrelated pre-existing Ruff findings and were not mass-formatted.

**Scope review:** normalized line endings only in task-owned files, confirmed no whitespace errors in tracked task diffs, and did not touch production DB, DNS, deploy configuration, migrations, commits, pushes, or other agents' files.

**Status:** done.
