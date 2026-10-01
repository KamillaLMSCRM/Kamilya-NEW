# Personal assignment browser continuity V1

Status: Accepted. Approved by: product owner, 2026-10-01 current chat.
Amends ADR-0022's no-cookie consequence only; predecessor remains historical.
Root/module owner: root. Reviewer: independent boundary reviewer and persistent
Test & Evidence Runner. Root approves technical addenda inside this scope; the
product owner approves any changed business deadline, data or authority boundary.

## Responsibility and interface

Restore the SAME bounded personal-assignment student session after page reload.
Map: PIN exchange -> browser cookie policy -> auth refresh -> existing exact
credential/enrollment authentication and read policy -> current student payload.
No new account, ordinary refresh credential, session extension, role capability,
database table, migration, worker, provider or payment configuration.

Inputs: trusted-origin JSON PIN exchange and credentialed /auth/refresh.
Outputs: existing access JWT, current student payload and remaining JWT seconds.
Stateless server restoration consumes existing enrollment/credential owners;
exchange retains its existing first-entry transaction and audit semantics.
Browser policy owns one host-only HttpOnly/Secure cookie at /api/v1/auth with the
existing same-site or explicitly configured DEV partitioned cross-site profile.
The cookie can outlive its signed JWT only to retain a fail-closed context marker:
JWT expiry NEVER moves. No token or PIN in JS persistent storage or logs.

## Invariants and transitions

PIN -> bounded student; reload -> same student and JWT; expired/revoked/cancelled
or mismatched assignment -> 401, NEVER prior methodologist/platform fallback.
An explicit successful ordinary account login or logout clears assignment context.
Restoration verifies signed type/auth_method/student role, tenant/user/credential
and exact enrollment plus current read policy before returning identity.
Completed enrollment retains existing own-result read behavior, never learning
mutations. Link expiry and started completion window remain independent.
Role switch and impersonation exit cannot turn assignment context into an ordinary
session. Assigned roles in this limited payload are only student.

## Impact and negative space

- Assignment exchange: compatible cookie extension, trusted-browser enforcement,
  credentials include on the web request; no new window or reissue allowance.
- Browser auth: assignment priority before ordinary/impersonation refresh; no
  fallback on assignment failure; explicit account issuance/logout clear context.
- Ordinary refresh/impersonation: unchanged when no assignment context exists.
- Existing core auth/read guards: consumed unchanged for revocation/RLS checks.
- Enrollment records/deadlines, email, AI, workers, customer data, billing: no change.

Errors: uniform unauthenticated response for invalid restoration; trusted-origin
403/JSON400 before exchange effects; DB failure must not yield identity/fallback.
Concurrency/idempotency: repeated restoration returns identical JWT and does not
rotate cookies, write policy, restart deadlines, or schedule work. Existing web
refresh lock coordinates tabs. Cookie context is shared by browser tabs, not
tab-isolated; deliberately switching account affects subsequent tab restores.
Performance/configuration: existing fixed assignment TTL and browser policy only.
Observability: sanitized counts/status/SHA; never log credential payloads.
Rollout: additive code-only; DEV before KZ production, current release retained
as rollback. Rollback to no-cookie code loses continuity, not enrollment history.

## Verification and ownership

Read/write scope: auth/browser_session.py, auth/router.py, enrollments/router.py,
enrollments/access_service.py, web access page/auth comments, named focused API/web
tests, plus canonical release/docs managed by root. No other module writes.
Focused seam tests: old-role cookie + assignment, student-only payload, unchanged
JWT/remaining expiry, invalid/expired/revoked/policy401 without fallback, trusted
origin rejection, cookie security/profile/clear, role-switch403 and ordinary
refresh/impersonation regression. Integration exercises real auth/enrollment RLS
in approved Supabase isolation or immutable CI, never workstation PostgreSQL.
Critical journey: ordinary methodologist -> personal learner entry -> reload ->
same student/course, responsive native learning/result readback in synthetic DEV
and production; deadline/revocation negatives without resetting existing fixtures.
Candidate full web suite/build/type, auth/backend suite/quality and release gates.

Ready: approved contract, scoped graph/source flow, exact baseline and RED.
Done: GREEN + independent review + full gates + exact DEV/production identity and
live journey evidence; honest labels for external gates, no assertion-only PASS.
Stop: unexpected module/data ownership, billing/destructive/customer scope,
failed security/identity gate or unknown mutation outcome. Root records disposition
before any changed contract; product owner authority is never inferred.
