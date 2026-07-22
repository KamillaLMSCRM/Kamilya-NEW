# AI jobs RBAC hardening

Date: 2026-07-21

Status: completed with WebSocket close-code correction

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

## Production follow-up - observable WebSocket close codes (2026-07-22)

### Follow-up plan

1. Use Graphify and the actual AI router/TestClient patterns to confirm how pre-upgrade close calls are observed by a real ASGI WebSocket client.
2. Add a FastAPI/Starlette TestClient regression for missing token, denied role, and tenant-scoped not-found close codes; capture the failing pre-fix behavior.
3. Preserve authorization and job lookup before data delivery, but complete the WebSocket upgrade before sending the documented application close frame.
4. Retain and run the fresh-session polling/RLS regressions, focused AI/RBAC tests, relevant broader tests, lint/compile checks, Graphify refresh, and final scoped diff inspection.

### Follow-up step 1 report - root cause and selected context

**Graphify selected:** `apps/api/app/modules/ai/router.py`, `apps/api/tests/test_ai_jobs_rbac.py`, `apps/api/app/main.py`, and `apps/api/tests/test_integration.py`.

**Confirmed:** Starlette treats `websocket.close()` before `websocket.accept()` as an HTTP WebSocket denial rather than a WebSocket close frame. Real clients therefore do not receive application codes 4001/4003/4004. Authentication and tenant-scoped lookup ordering are otherwise correct.

**Status:** done.

### Follow-up step 2 report - failing client regression

**Changed:** added a real FastAPI/Starlette TestClient regression covering missing token (4001), denied admin role (4003), and tenant-scoped not-found (4004). The denied-role case also asserts that no job lookup occurs.

**Red check:** `pytest tests/test_ai_jobs_rbac.py -k client_observes_application_close_codes -q` failed all three cases because `websocket_connect()` received a close event before an accept event; the application codes were not delivered after a completed WebSocket upgrade.

**Status:** done.

### Follow-up step 3 report - handshake sequencing fix

**Changed:** rejection paths now use one helper that accepts the WebSocket only after the missing-token, role-denial, or scoped not-found decision has been made, then immediately sends the documented application close frame. Denied roles still stop before job lookup, and authorized tenant users still receive the same 4004 for nonexistent and cross-tenant jobs.

**Green check:** the real-client close-code tests and both fresh-session polling/RLS paths passed (`5 passed`).

**Status:** done.

### Follow-up step 4 report - verification

**Passed:**

- Real-client close codes plus fresh-session RLS polling: 5 passed.
- Focused AI/source/RBAC suite: 75 passed.
- Full selected TestClient integration file: 13 passed, with two unrelated Pydantic deprecation warnings.
- `ruff check tests/test_ai_jobs_rbac.py` - passed.
- Critical router lint (`E9,F63,F7,F82`) - passed.
- `python -m compileall -q app/modules/ai/router.py tests/test_ai_jobs_rbac.py` - passed.
- Scoped `git diff --check` - passed.

**Graphify:** refreshed after implementation; `graphify-out/` remains untracked.

**Final inspection:** missing token, denied role, and scoped not-found paths now deliver 4001/4003/4004 after upgrade. No rejected connection receives job data; denied roles never query the job; nonexistent and cross-tenant jobs remain indistinguishable; fresh-session polling authentication/RLS behavior is unchanged.

**Status:** done.

## Constraints

- Preserve unrelated worktree changes.
- No migration, production, database, deployment, commit, or push.
- Do not introduce per-user AI job ownership policy without an ADR.
- Keep tenant filtering as defense in depth; cross-tenant job identifiers must resolve as not found.
- Keep retry, Voyage, and ingestion changes out of this task.

## Second production follow-up - real TCP close-frame delivery (2026-07-22)

### Transport correction plan

1. Use Graphify to select the WebSocket authorization and transport path, then inspect the deployed implementation, installed FastAPI/Starlette/Uvicorn/WebSockets versions, and production protocol selection.
2. Reproduce missing-token, denied-role, and scoped-not-found closes through a real Uvicorn TCP server bound to an ephemeral port and a real `websockets` client; compare immediate close, event-loop yield, and application-message sequencing where needed.
3. Add a failing real-network regression against the actual AI WebSocket route, apply the smallest transport-compatible fix, and retain the fresh-session polling/RLS tests.
4. Run focused and broader relevant tests plus lint/compile/diff gates, refresh Graphify, and inspect the final scoped changes without committing, pushing, deploying, or changing the database.

### Transport correction step 1 report - production and local diagnosis

**Graphify selected:** `apps/api/app/modules/ai/router.py`, `apps/api/tests/test_ai_jobs_rbac.py`, `apps/api/app/core/auth.py`, `apps/api/app/core/db.py`, and `apps/api/app/modules/ai/job_service.py`.

**Installed/deployed stack:** FastAPI 0.115.14, Starlette 0.46.2, Uvicorn 0.32.1, and websockets 14.2. Production starts Uvicorn with its default `auto` WebSocket selection, which resolves to Uvicorn's `websockets` protocol; `wsproto` is not installed.

**Reproduced:** a read-only real `websockets` client probe against deployed commit `62095663` upgraded successfully and received an empty 1005 close for the missing-token path. The same immediate accept-and-close implementation delivered 4001/4003/4004 correctly through a local real Uvicorn TCP server on an ephemeral port.

**Root cause boundary:** Uvicorn's actual ASGI transport waits for its handshake-completed event before writing either an application frame or close frame, so an event-loop-only yield does not correct a missing handshake wait. The discrepancy occurs beyond the local Uvicorn transport on the Render edge's immediate post-upgrade close path. A dependency/backend adjustment is unsupported by the installed stack and not indicated by the local wire behavior. The selected compatibility barrier is a generic application data frame before the close frame.

**Status:** done.

### Transport correction step 2 report - failing real-network regression

**Changed:** added a real Uvicorn server regression using a pre-bound ephemeral TCP socket and the installed `websockets` client. It covers missing token (4001), denied admin active role (4003), and scoped not-found (4004), and asserts that denied paths perform no job lookup.

**Red check:** the real-network test failed against the deployed implementation because its first receive observed the immediate close instead of an application error event.

**Status:** done.

### Transport correction step 3 report - compatibility barrier

**Changed:** the shared rejection helper now sends a generic `{type, code, message}` error event after upgrade and before the unchanged application close frame. It contains no job data. Denied roles still stop before lookup, tenant-scoped not-found remains indistinguishable from cross-tenant access, and the fresh-session polling/RLS flow is unchanged.

**Green check:** the real-TCP close matrix, TestClient close matrix, and tenant/platform multi-iteration polling checks passed together (6 passed).

**Status:** done.

### Transport correction step 4 report - verification

**Passed:**

- `pytest tests/test_ai_jobs_rbac.py -q` - 24 passed.
- Focused AI/source/RBAC suite - 76 passed.
- `pytest tests/test_integration.py -q` - 13 passed.
- `ruff check tests/test_ai_jobs_rbac.py` - passed.
- Critical router lint (`E9,F63,F7,F82`) - passed.
- `python -m compileall -q app/modules/ai/router.py tests/test_ai_jobs_rbac.py` - passed.
- Scoped `git diff --check` - passed.

**Known repository lint debt:** unrestricted whole-file router lint reports 45 pre-existing findings outside this change; no unrelated cleanup was performed.

**Environment-limited:** the document-compatibility and superadmin-lifecycle DB-backed integration files stop during fixture setup because local PostgreSQL rejects the configured test login. No environment or database configuration was changed.

**Graphify:** refreshed after the implementation; `graphify-out/` remains untracked.

**Final inspection:** no connection receives job data before authorization. Missing token and denied role never query a job; not-found lookup remains tenant-scoped; tenant and platform polling sessions still re-establish their DB security context on every iteration.

**Status:** done.
