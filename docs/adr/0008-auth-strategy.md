# ADR-0008: Authentication strategy — JWT + httpOnly refresh cookie

- **Status:** Accepted (after 2026-06-28 hardening)
- **Date:** 2026-06-28
- **Context:** AGENTS.md §Authz, audit §4.1, §4.2

## Decision

We use **JWT access tokens + httpOnly refresh cookies** for session
management. The previous design (access token in localStorage + non-
httpOnly cookie) was replaced due to multiple XSS-exfiltration risks
flagged in audit §4.1.

### Token storage

| Token | Lifetime | Storage | Where |
|-------|----------|---------|-------|
| Access | 15 min | In-memory only (Zustand store) | Browser process memory |
| Refresh | 30 days | httpOnly + Secure + SameSite=Strict cookie | Path: `/api/v1/auth` only |

The access token is **never** written to localStorage, sessionStorage,
or non-httpOnly cookies. JS code cannot read the refresh token at all.

### Token claims

Required claims (validated by `decode_token`):
- `sub` — user UUID
- `tenant_id` — UUID or null (superadmin)
- `roles` — list of role strings
- `exp` — expiry (15 min from issue for access, 30 days for refresh)
- `iat`, `nbf`, `jti` — standard JWT claims
- `aud` = `kamilya-lms` — service identifier
- `iss` = `kamilya-lms` — issuer identifier

Algorithm is **HS256** (explicit allow-list). JWT_SECRET must be ≥32
chars; the `Settings` validator rejects shorter secrets at startup.

### Authentication flows

1. **Login** (`POST /api/v1/auth/login`):
   - Validate credentials.
   - Issue access token (15 min) and refresh token (30 days).
   - Set refresh token as httpOnly cookie.
   - Return access token in JSON body.

2. **Telegram bot auth** (`POST /api/v1/auth/check-code`):
   - User pastes the 6-digit code in the web UI.
   - On verification, issue access token. No refresh token here
     (telegram sessions are short-lived by design; if the user
     closes the tab they re-link via Telegram).

3. **Refresh** (`POST /api/v1/auth/refresh`):
   - Reads refresh token from httpOnly cookie (preferred) or
     request body (legacy compatibility).
   - Rotates the refresh token (returns a new pair). Old refresh
     token is no longer accepted — JWT signature changed.

4. **Logout** (`POST /api/v1/auth/logout`):
   - Blacklists the refresh token (deletes session row).
   - Clears the cookie.

### Defense-in-depth

- **CSRF:** SameSite=Strict cookie + refresh cookie scoped to
  `/api/v1/auth/*` paths only. Cross-origin requests won't carry
  the cookie.
- **Token theft via XSS:** Access token is in memory only; refresh
  token is httpOnly. An XSS payload can call /refresh once before
  re-login is forced.
- **Replay:** Refresh tokens are stateless JWTs but rotation on
  each use means a stolen token stops working after one successful
  refresh.
- **Algorithm confusion:** `decode_token` explicit `[HS256]`
  allow-list. Config validator rejects non-HMAC algorithms and
  'none'. `aud` and `iss` claims validated against settings.

### Tenant context propagation

On every authenticated request, `get_current_user` calls
`set_current_tenant(tenant_id)` (Postgres `set_config('app.tenant_id')`).
After migration 0033 (FORCE ROW LEVEL SECURITY + lms_app role),
this context becomes mandatory — queries without it return zero rows
from RLS-protected tables.

## Alternatives considered

- **Session cookies with server-side state.** More secure but
  requires a sticky-session deployment; horizontal scaling adds
  Redis session store complexity. JWT chosen for statelessness.
- **Refresh token rotation in DB (revocation list).** Stronger but
  adds a DB hit on every refresh. Current design relies on JWT
  signature rotation (compromise of secret = all tokens can be
  minted by attacker, which is true anyway with stateless JWT).
- **Short-lived access tokens (5 min) instead of 15.** Marginal
  security gain at significant UX cost (more frequent /refresh
  round-trips). 15 min is the sweet spot.

## Open items

- **Refresh-token fingerprint binding.** A stolen refresh cookie +
  access token could be used from another browser. Mitigation:
  bind refresh to user-agent / IP hash. Not implemented in v1;
  the httpOnly cookie + SameSite=Strict + 30-day rotation gives
  adequate baseline.
- **MFA for superadmin login.** Currently email/password only. Add
  TOTP or WebAuthn in v1.1.