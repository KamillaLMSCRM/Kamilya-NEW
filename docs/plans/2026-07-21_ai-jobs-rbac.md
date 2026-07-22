# AI jobs RBAC hardening

Date: 2026-07-21

Status: completed with WebSocket polling correction

## Scope

Close the confirmed authorization gap for AI course generation and job access without changing migrations, production infrastructure, provider failover, retry, or ingestion behavior.

## Plan

1. Inspect the canonical active-role authorization path, existing AI HTTP/WebSocket behavior, and nearby test helpers.
2. Add one explicit reusable AI content-management role guard for `methodologist` and `superadmin`, and apply it to create/list/get/cancel job endpoints.
3. Enforce the same active-role and tenant-scoped not-found semantics during the WebSocket handshake, before accepting the connection.
4. Add focused regression coverage for the role matrix, active-role behavior, same-tenant access, cross-tenant 404 behavior, and WebSocket denial/access.
5. Run targeted AI/source/RBAC tests, inspect the final diff and worktree, and record verification results here.

## Step 1 report — authorization and test-path inspection

**Changed:** no production code yet. Confirmed that HTTP role dependencies consume the server-validated active-role view returned by `get_current_user`, while the AI jobs WebSocket decoded JWT claims directly and accepted the connection without loading the user or validating `active_role` against `user_roles`. Confirmed that the router-level tenant dependency also prevented a platform superadmin from reaching AI job endpoints despite the requested role canon.

**Checks:** inspected `app/core/auth.py`, all AI HTTP and WebSocket routes, `AIJob` scoping, multi-role tests, and integration fixtures. The worktree contained three unrelated untracked plan files and they remain untouched.

**Status:** done.

## Step 2 report - implementation

**Changed:** added the shared `require_ai_job_access` dependency for `methodologist` and `superadmin` to generate/list/get/cancel. Split tenant-only non-job routes into a nested router so platform superadmins can reach the authorized job surface without weakening tenant requirements elsewhere. Tenant users retain explicit job-query filtering; platform superadmins retain the canonical unscoped platform view.

**WebSocket:** authentication now loads the user through the same database-backed token and active-role validation used by HTTP, applies the shared role guard before `accept()`, and performs the tenant-scoped job lookup before accepting. Unauthorized roles close with 4003; missing or cross-tenant jobs close with 4004 and are not disclosed.

**Status:** done.

## Step 3 report - regression coverage

**Changed:** added `tests/test_ai_jobs_rbac.py` with coverage for the role matrix, shared dependency wiring across all four HTTP handlers, active-role-over-primary-role behavior, tenant query scoping, cross-tenant 404 handling for generate/get/cancel, and WebSocket role/cross-tenant/allowed access.

**Red/green:** the new suite initially failed 15 tests against the prior implementation, then passed all 18 after the authorization changes.

**Status:** done.

## Step 4 report - verification

**Passed:**

- `pytest tests/test_ai_jobs_rbac.py tests/test_trial_and_ai_dispatch.py tests/test_methodologist_role.py tests/unit/test_multi_role.py tests/unit/test_document_compatibility.py tests/test_course_release_policy.py tests/test_llm_failover.py -q` - 70 passed.
- `ruff check tests/test_ai_jobs_rbac.py` - passed.
- `python -m compileall -q app/modules/ai/router.py tests/test_ai_jobs_rbac.py` - passed.
- `git diff --check` for the task files - passed.

**Environment-limited:** `tests/integration/test_document_compatibility_api.py` could not set up because local PostgreSQL rejected the configured test login. No environment or database values were changed.

**Final inspection:** AI routes remain registered once; unrelated worktree changes were preserved; no migration, commit, push, production, deployment, or database action was performed.

**Status:** done.

## Separate backlog

- Retry behavior.
- Voyage/provider failover behavior.
- Document ingestion changes.

## Correction - WebSocket polling RLS context (2026-07-22)

### Correction plan

1. Use Graphify to select the WebSocket, authentication, RLS-context, job lookup, and regression-test path; confirm the defect against the implementation.
2. Add a non-terminal, multi-iteration regression test for tenant methodologist and platform superadmin polling sessions and capture the failing result.
3. Re-authenticate and re-authorize the token inside every fresh polling session so its transaction receives the correct tenant or platform-superadmin database context before the job query, without holding a session during the WebSocket wait.
4. Refresh Graphify, run the focused AI/RBAC and relevant integration tests, and inspect the final scoped diff.

### Correction step 1 report - context selection and root cause

**Graphify selected:** `apps/api/app/modules/ai/router.py`, `apps/api/app/modules/ai/job_service.py`, `apps/api/app/core/auth.py`, `apps/api/app/core/db.py`, `apps/api/alembic/versions/0019_rls_policies.py`, `apps/api/alembic/versions/0033_force_rls_and_lms_app_role.py`, and `apps/api/tests/test_ai_jobs_rbac.py`.

**Confirmed:** the handshake calls the canonical authentication path, which establishes transaction-local tenant or platform-superadmin context. After a non-terminal message, the loop closes that session, sleeps, opens a fresh session, and calls `get_ai_job` directly. Because the RLS settings are transaction-local and `ai_jobs` uses forced RLS, the fresh query lacks the required context and can return no job.

**Status:** done.

### Correction step 2 report - failing regression

**Changed:** added a parameterized non-terminal WebSocket test that uses distinct handshake and polling sessions. Its authentication double marks each session with the expected tenant or platform-superadmin context, and the job lookup refuses an unmarked fresh session.

**Red check:** `pytest tests/test_ai_jobs_rbac.py -k reestablishes_security_context_for_each_poll -q` failed for both tenant methodologist and platform superadmin because authentication/context setup ran only for the handshake session.

**Status:** done.

### Correction step 3 report - polling context fix

**Changed:** every fresh polling session now runs the same database-backed token validation, active-role validation, trial/access validation, and shared AI-job role guard as the handshake before querying the job. The lookup derives its tenant scope from the freshly validated user. The session is opened only after the polling delay and closes at the end of that iteration.

**Green check:** `pytest tests/test_ai_jobs_rbac.py -k reestablishes_security_context_for_each_poll -q` passed for both tenant methodologist and platform superadmin.

**Status:** done.

### Correction step 4 report - verification

**Passed:**

- `pytest tests/test_ai_jobs_rbac.py tests/test_trial_and_ai_dispatch.py tests/test_methodologist_role.py tests/unit/test_multi_role.py tests/unit/test_document_compatibility.py tests/test_course_release_policy.py tests/test_llm_failover.py -q` - 72 passed.
- `ruff check tests/test_ai_jobs_rbac.py` - passed.
- `python -m compileall -q app/modules/ai/router.py tests/test_ai_jobs_rbac.py` - passed.
- Scoped `git diff --check` - passed.

**Integration attempts:** `tests/integration/test_document_compatibility_api.py` and `tests/integration/test_superadmin_lifecycle.py` both stopped during fixture setup because local PostgreSQL rejected the configured test login. No DB or environment configuration was changed.

**Graphify:** refreshed with `graphify update .`; `graphify-out/` remains untracked.

**Final inspection:** pre-accept authorization and tenant 404 behavior remain intact; polling revalidates active-role access and establishes fresh transaction-local RLS context; no session remains open during the polling delay.

**Status:** done.

## Constraints

- Preserve unrelated worktree changes.
- No migration, production, database, deployment, commit, or push.
- Do not introduce per-user AI job ownership policy without an ADR.
- Keep tenant filtering as defense in depth; cross-tenant job identifiers must resolve as not found.
- Keep retry, Voyage, and ingestion changes out of this task.
