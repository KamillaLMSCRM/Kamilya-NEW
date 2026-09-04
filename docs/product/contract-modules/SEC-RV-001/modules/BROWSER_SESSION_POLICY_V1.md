# Browser session policy mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `BROWSER-SESSION-POLICY` |
| Name | `BrowserSessionPolicy` |
| Status | Accepted |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Product owner via SEC-RV-001 continuation on 2026-09-04 |
| Change control | Proposal -> root review -> V2/addendum or cancellation |
| Owning epic | `SEC-RV-001` |

## Responsibility [Core]

Apply one fail-closed policy to every browser request that creates, rotates, reads or
clears the refresh-session cookie.

## Non-responsibilities [Core]

Credential verification, JWT construction, refresh-session persistence, user/tenant
authorization, CORS and frontend token storage remain owned by their existing modules.

## User-visible contribution [Core]

Valid users retain normal login, refresh, role-switch, invitation and trial flows while
cross-site requests cannot create, rotate or revoke browser sessions.

## External interface [Core]

```text
BrowserSessionPolicy.enforce_request(request) -> None
BrowserSessionPolicy.read_refresh_token(request, body_token=None) -> str | None
BrowserSessionPolicy.set_refresh_cookie(response, token) -> None
BrowserSessionPolicy.clear_refresh_cookie(response) -> None
```

Errors expose a stable code, HTTP 400/403 status and non-sensitive public detail.

## Configuration [Core]

| Setting | Meaning |
|---|---|
| `PUBLIC_URL` | Canonical LMS application origin; the sole accepted auth origin in ordinary KZ production |
| `AUTH_BROWSER_ORIGINS` | Exact trusted browser origins; independent of CORS |
| `AUTH_COOKIE_PROFILE` | `same_site` for KZ production; `cross_site` only for an explicit development topology |
| `AUTH_COOKIE_SECURE` | HTTPS-only cookie switch; mandatory in production and in `cross_site` mode |
| `AUTH_REFRESH_BODY_FALLBACK` | Legacy non-cookie client compatibility; forbidden in production |

## Invariants [Core]

- A supplied Origin must be a syntactically valid HTTP(S) origin and exactly trusted.
- Outside the named Render development topology, production requires the trusted-origin
  set to equal the canonical `PUBLIC_URL` origin exactly.
- Public landing origins are not LMS auth origins and cannot refresh or receive sessions.
- Production browser-session requests require Origin and JSON content type.
- `Sec-Fetch-Site: cross-site` is rejected before auth/DB/session side effects unless
  an exact trusted Origin uses the explicit non-production `cross_site` profile.
- The refresh cookie is HttpOnly, path-scoped to `/api/v1/auth`, bounded by configured
  refresh lifetime and has no Domain attribute.
- `same_site` uses `SameSite=Lax`; `cross_site` uses `SameSite=None`, Secure and
  Partitioned, and is available only to the explicit `render-development`
  deployment topology or a non-production application environment.
- Cookie clearing repeats the creation scope/security attributes exactly.
- Cookie input wins over any legacy body value; production never accepts the body value.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| No browser session | Valid issuing request | Session cookie issued | Request and profile accepted | Existing route owns session row/commit |
| Active browser session | Valid refresh/role switch | Rotated session cookie | Request and token source accepted | Existing route owns rotation |
| Active/invalid session | Valid logout | Cookie cleared | Request accepted | Existing route owns best-effort revocation |
| Any | Invalid browser request/profile | Rejected | Policy failure | No route-owned auth/DB/session side effect |

## Error modes [Core]

| Code | HTTP | Meaning |
|---|---:|---|
| `browser_origin_required` | 403 | Production request has no Origin |
| `browser_origin_forbidden` | 403 | Origin is malformed, null or not trusted |
| `cross_site_request_forbidden` | 403 | Fetch Metadata reports a cross-site request |
| `browser_json_required` | 400 | Production request is not JSON |
| `legacy_refresh_body_forbidden` | 400 | Refresh token was supplied in the body where disabled |

## Dependencies and adapters [Extended]

FastAPI/Starlette request and response objects plus validated application settings. No
port is introduced because there is one in-process implementation.

## Existing-module impact addendum [Extended]

See `../impact/BROWSER_SESSION_INTEGRATION_V1.md`.

## Security and privacy [Core]

Origin is treated as untrusted input. Tokens and cookie values are never logged or
included in errors. CORS is explicitly not treated as authentication or CSRF defense.

## Verification [Core]

Interface tests cover trusted/hostile/missing/malformed origins, Fetch Metadata,
content type, both cookie profiles, set/clear symmetry and legacy body behavior. Route
tests prove hostile Origin is rejected before credential/session work, including
access-token user resolution and its RLS/DB context. Existing auth,
invitation and tenant-registration tests remain green.

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | Auth/session routes, settings, frontend auth client and auth tests |
| Write scope | Browser-session module, settings/examples, session-issuing routes/tests, docs/changelog |
| Forbidden scope | DB migrations, CORS widening, provider env mutation, deployment, secrets |
| Required checks | Policy interface tests, route atomic rejection, auth unit regression, quality baseline |
| Stop conditions | Production requires a cross-site topology or non-browser body-token client |
| Handoff evidence | Exact tests and explicit DB/browser/production gaps |

## Rollout and rollback [Extended]

Production requires the same-site KZ topology and explicit trusted origins. Legacy
cross-site development can opt into the isolated `cross_site` profile. Rollback uses the
prior application image; no data migration or historical rewrite is involved.

## Definition of Ready [Core]

Trusted-origin, cookie-profile, token-source, error and integration seams are accepted.

## Definition of Done [Core]

All refresh-cookie routes use this module; hostile browser requests fail before route
side effects; cookie create/clear attributes match; focused and regression checks pass;
live browser and production configuration remain explicit release gates.
