# Browser session integration impact addendum V1

Status: Accepted
Approved by: Product owner via SEC-RV-001 continuation on 2026-09-04

All routes that issue, rotate, consume or clear `kamilya_refresh` validate through
`BrowserSessionPolicy` before credential lookup or route-owned DB/session effects.
Cookie construction moves out of auth routers into the shared module; invitation and
tenant registration stop importing private router helpers. Production accepts only
the exact canonical `PUBLIC_URL` origin, JSON requests and the same-site secure cookie profile;
legacy refresh tokens in JSON bodies are rejected. Development/test may use an explicit
cross-site profile or body fallback. The tracked Render development service explicitly
trusts only its paired Vercel development frontend and uses the cross-site cookie profile.
The role-switch dependency graph enforces the browser policy before resolving the
access-token user, so hostile requests cannot trigger user/RLS database lookup.
JWT claims, session tables, login response payloads,
tenant/RLS rules, CORS behavior and frontend access-token storage remain unchanged.
