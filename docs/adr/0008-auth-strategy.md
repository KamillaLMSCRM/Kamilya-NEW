# ADR-0008: Authentication strategy — JWT, refresh cookie, and active role

- **Status:** Accepted
- **Date:** 2026-06-28
- **Last consolidated:** 2026-07-21
- **Context:** Browser-session security, tenant context propagation, and
  multi-role tenant sessions

## Decision

Kamilya LMS uses a short-lived JWT access token with a browser refresh cookie.
The access token stays in memory; the refresh token is not exposed to
JavaScript. The browser application and current API are cross-site, so cookie
attributes must reflect that deployment topology.

## Token storage and session transport

| Token | Runtime lifetime | Storage | Runtime transport |
|---|---|---|---|
| Access | 15 minutes | In-memory frontend auth state | Authorization bearer header |
| Refresh | 30 days | Browser cookie; never readable by JavaScript | Cookie path /api/v1/auth |

The current auth router sets the refresh cookie with all of the following
attributes:

- HttpOnly
- Secure
- SameSite=None
- Partitioned
- Path=/api/v1/auth

SameSite=Strict is not the current behavior and must not be described as the
CSRF control. Because the cookie is eligible for the cross-site browser/API
flow, origin and CORS controls around auth requests remain part of the
deployment security boundary. Scoping the cookie to the auth path reduces its
send surface but does not replace request-origin controls.

The access token is never stored in localStorage, sessionStorage, or a
non-HttpOnly cookie.

## Token contents and validation

The token encoder adds standard claims exp, iat, nbf, and jti; time claims are
NumericDate integers. It sets the configured audience and issuer. The decoder
uses a one-algorithm allow-list from application settings and requires valid
sub, exp, iat, aud, and iss claims.

Session payloads use these application claims where applicable:

- sub: user identifier;
- tenant_id: tenant identifier, or null for a platform superadmin;
- roles: assigned-role snapshot in access tokens;
- active_role: the selected tenant working mode;
- type=refresh: refresh-token marker.

An access decision is never made from the client payload alone. The current
user is loaded from the database and role guards evaluate the active role.
Tenant context is established through the database set_current_tenant(...)
function before tenant-scoped access.

## Authentication and session flows

### Password and email OTP login

The password login and email-OTP verification flows issue an access token and
a refresh token, set the refresh cookie, and return the session payload needed
by the frontend.

### Telegram code login

A verified Telegram code also issues both an access token and a refresh token,
sets the same refresh cookie, and returns the user session payload. The older
description of Telegram as an access-token-only, short-lived browser session is
obsolete.

### Refresh

POST /api/v1/auth/refresh prefers the refresh cookie and accepts a request body
token only for legacy compatibility. It validates the refresh-token type and
current user, then issues a fresh access/refresh pair and refreshes the cookie.

The current implementation is stateless at refresh validation: it validates
the JWT and user rather than a server-side refresh-session record. Therefore,
documentation must not claim that issuing a replacement token alone makes an
older refresh token unusable. Any stronger single-use rotation or server-side
revocation requirement needs a dedicated runtime change.

### Logout

POST /api/v1/auth/logout clears the browser refresh cookie. It also performs
the existing best-effort refresh-token blacklist cleanup when a token is
available; this cleanup is not equivalent to server-side validation on every
refresh.

## Active role and multi-role sessions

The multi-role product policy is defined by ADR-0012.

- A new tenant login starts with users.role, the primary role.
- POST /api/v1/auth/switch-role accepts only a role returned from the account's
  current user_roles assignment set.
- A successful switch issues new access and refresh tokens with the requested
  active_role, sets the refresh cookie, and returns an updated user payload.
- Refresh reads the token's active role and preserves it when it remains among
  the account's assigned roles.
- require_role(...) evaluates one active role, not the union of all assigned
  roles.

Current request validation explicitly checks a non-primary active_role against
user_roles before presenting that active mode to role guards. ADR-0012 requires
the selected mode to be assignment-backed in all cases; applying that
requirement uniformly, including the primary-role path, is backend conformance
work rather than a documentation exception.

## Tenant context propagation

On an authenticated tenant request, get_current_user invokes
set_current_tenant(tenant_id) for the database session. With FORCE RLS and the
lms_app runtime role (ADR-0004), this context is required for tenant-scoped
visibility.

A platform superadmin has no ordinary tenant context. Platform APIs must use
their dedicated authorization paths; tenant work is performed through the
explicit impersonation flow rather than by treating superadmin as an unscoped
tenant role.

## Acceptance criteria for auth changes

1. Every browser login flow that claims session persistence returns an access
   token and sets the refresh cookie with the current attributes.
2. A full browser reload followed by refresh restores a valid session.
3. Refresh works from the cookie; the legacy body fallback remains covered only
   while it is supported.
4. A role switch rejects an unassigned role, rotates the session, refreshes the
   cookie, and updates the active role in the frontend payload.
5. Refresh preserves an assigned active role, and tenant authorization uses the
   active role rather than an aggregate role union.
6. Authenticated tenant requests establish tenant context and cross-tenant
   resource access returns 404.
7. Tests must assert the actual cookie attributes. Do not assert
   SameSite=Strict, omit Partitioned, or treat Telegram as access-only.

## Open decisions

- **Stateful refresh revocation / single-use rotation.** The current stateless
  refresh validation does not invalidate an older signed refresh token merely
  because a replacement was issued. Product and security owners must decide
  whether v1 requires a server-side session or deny-list check at refresh time.
- **Uniform primary-role assignment validation.** ADR-0012 requires every
  selected mode to be assignment-backed; the current primary-role path should
  be brought to the same verification standard in a backend task.
- **MFA for superadmin login.** TOTP or WebAuthn remains a future platform
  security decision.

## Cross-references

- [ADR-0003](./0003-multitenant.md): tenant isolation
- [ADR-0004](./0004-rls-force-and-app-role.md): FORCE RLS and `lms_app`
- [ADR-0012](./0012-rbac-admin-vs-methodologist.md): role ownership, active role, and role-matrix tests
- `apps/api/app/core/auth.py`
- `apps/api/app/modules/auth/router.py`
- `apps/api/app/modules/auth/service.py`
