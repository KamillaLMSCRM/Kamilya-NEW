# Kamilya LMS — Lessons Learned

> Per-project memory of bugs that took multiple fix attempts to resolve.
> Add a new entry whenever a fix didn't work on the first try.
>
> Pattern: **Symptom → Root Cause → Fix → Detection Rule**.
> "Detection Rule" is the most important part — it's the cheap check that
> would have caught this on the first attempt.

---

## 2026-06-29 — Telegram login: 4 fix attempts to find the real bug

### Symptom

User enters the 6-digit code in the Telegram bot. Bot replies
"✅ Вход выполнен успешно!". The frontend polling `/auth/check-code`
returns `verified=true` and an `access_token`. But on the **next page
reload** the user is bounced back to `/login`, and the console shows
`POST /api/v1/auth/refresh → 401`.

### Root cause

Three independent bugs stacked on top of each other:

1. **`RefreshRequest.refresh_token: str` was required.** The frontend
   `lib/auth.ts::restoreSession` sends `JSON.stringify({})` because
   the canonical token source is the httpOnly cookie. Pydantic
   rejected the body with **422** before the router could look at
   the cookie. So the cookie round-trip never worked end-to-end —
   only `access_token` in the in-memory store did.
2. **Three login endpoints (`/check-code`, `/superadmin-login`,
   `/demo-login`) never called `_set_refresh_cookie` and returned
   `JSONResponse(content=...)` inline.** Even after fixing the
   schema, the httpOnly cookie never reached the browser because the
   injected `response: Response` parameter (where the cookie was
   written) was discarded by the explicit `JSONResponse` return.
3. **Vercel `rewrite()` strips `Set-Cookie` on proxied responses.**
   The early rewrite proxying `/api/v1/*` to Render worked for
   status codes but silently dropped `Set-Cookie` to prevent cache
   poisoning. The frontend's `fetch('/api/v1/auth/refresh')` reached
   the backend but the browser never saw the cookie.
4. **`NEXT_PUBLIC_API_URL` on Vercel ends in `/api`** (axios-style
   baseURL). My cross-origin fix initially built
   `${API_BASE}/api/v1/auth/refresh` which gave the doubled
   `/api/api/v1` path → 404. Should have been `${API_BASE}/v1/...`
   to match the axios convention.

### Fix

| # | Commit | File | Change |
|---|---|---|---|
| 1 | `5b7b26b` | `apps/api/app/modules/auth/schemas.py` | `refresh_token: str | None = None` |
| 2a | `f3e7a1a` | `apps/api/app/modules/auth/router.py::check_auth_code` | mint refresh_token, `_set_refresh_cookie`, return dict |
| 2b | `f3e7a1a` | `apps/api/app/modules/auth/superadmin_login.py` | duplicated `_set_refresh_cookie` (avoid circular import) |
| 2c | `0440f30` | `apps/api/app/modules/auth/router.py::demo_login` | same |
| 3 | `48c3536` | `apps/web/next.config.js`, `apps/web/src/lib/auth.ts` | drop rewrite, go cross-origin to Render directly |
| 4 | `e95e75b` | `apps/web/src/lib/auth.ts` | `${API_BASE}/v1/auth/refresh` (not `/api/v1/...`) |
| cookie-not-shadowed | `2fdb2cb` | `apps/api/app/modules/auth/router.py` | `return JSONResponse(...)` → `return dict` so the injected response (with its Set-Cookie) is preserved |

### Detection rule (cheap check before declaring "login works")

```bash
# After any login-flow change, do ALL of these in a browser:
# 1. POST /api/v1/auth/check-code or /demo-login with a verified code/role
# 2. Inspect Set-Cookie header in the response (curl -i)
# 3. Force a full page reload (F5)
# 4. Verify /api/v1/auth/refresh returns 200, NOT 401

# The single curl that would have caught bugs #1 and #2:
curl -i -X POST https://kamilya-lms-api.onrender.com/api/v1/auth/demo-login \
  -H "Content-Type: application/json" -H "Origin: https://app.kml.kz" \
  -d '{"role":"teacher"}' | grep -i "set-cookie"
# MUST contain: kamilya_refresh=...; HttpOnly; Path=/api/v1/auth
```

If this returns nothing, **do not declare the login flow fixed** —
the cookie round-trip is broken regardless of what the access_token
response body looks like.

### Iron Law (project rule)

> **No login-flow change is "done" until F5 keeps the user on
> /dashboard.** A 200 on the login endpoint proves nothing about
> session persistence — only F5 does.

---

## 2026-06-29 — Vercel autoDeploy works; Render autoDeploy is broken

### Symptom

`git push origin master` succeeds. Frontend (Vercel) auto-deploys
within ~1 minute. Backend (Render) stays on the previous deploy —
the new commit is not picked up.

### Root cause

Render's GitHub autoDeploy webhook stopped firing for this service.
Confirmed in Render API: `trigger: "api"` for the working deploys
and `trigger: "manual"` for everything since the webhook died.

### Fix

After every `git push` that touches `apps/api/**`:

```powershell
$env:RENDER_API_KEY = (Get-Content apps/api/.env `
  | Select-String 'RENDER_API_KEY' `
  | ForEach-Object { ($_ -split '=', 2)[1].Trim() })
$env:RENDER_SERVICE_ID = 'srv-d8rp8ej7uimc73fglid0'
$headers = @{ Authorization = "Bearer $env:RENDER_API_KEY"; Accept = 'application/json' }
Invoke-WebRequest `
  -Uri "https://api.render.com/v1/services/$env:RENDER_SERVICE_ID/deploys" `
  -Method POST -Headers $headers -UseBasicParsing
```

Or via the Render CLI (installed on this machine):

```powershell
render deploys create --service $env:RENDER_SERVICE_ID --wait
```

### Detection rule

After every push, before claiming a backend change is deployed:

```powershell
$deploys = Invoke-RestMethod `
  -Uri "https://api.render.com/v1/services/srv-d8rp8ej7uimc73fglid0/deploys?limit=1" `
  -Headers $headers
# Check that $deploys[0].commit.id starts with the commit you just pushed
```

If the latest Render deploy's commit hash doesn't start with the same
6 chars as `git rev-parse HEAD`, the backend is NOT updated — trigger
the deploy manually.

---

## 2026-06-29 — NEXT_PUBLIC_API_URL ends in `/api` on Vercel (convention gotcha)

### Symptom

Two different frontend code paths build different URLs from the same
`NEXT_PUBLIC_API_URL` env var:

- `axios` uses it as `baseURL` and prepends `/v1/...` per request
  → `…onrender.com/api/v1/auth/refresh` ✅
- `lib/auth.ts::fetch('/api/v1/auth/refresh')` (relative) used to
  work via Vercel rewrite, but after dropping the rewrite a manual
  `${API_BASE}/api/v1/auth/refresh` doubled the `/api` segment
  → `…onrender.com/api/api/v1/auth/refresh` → 404

### Fix

Match axios. Use `${API_BASE}/v1/auth/refresh` and
`${API_BASE}/v1/auth/logout` — no extra `/api`.

### Detection rule

When adding a new code path that builds an absolute API URL:

```typescript
const url = `${process.env.NEXT_PUBLIC_API_URL}/v1/...`; // ✅
const url = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/...`; // ❌ doubled
```

Grep before merge:
```bash
rg "NEXT_PUBLIC_API_URL" apps/web/src
# Every site must build the URL the same way. If you see both
# `${API_BASE}/v1/...` and `${API_BASE}/api/v1/...` in the same
# codebase, one of them is wrong.
```

---

## 2026-06-29 — Vercel `rewrites()` strip `Set-Cookie`

### Symptom

Backend returns `Set-Cookie: kamilya_refresh=...; HttpOnly` (verified
via direct curl). Browser `document.cookie` stays empty after the
same call routed through Vercel.

### Root cause

Vercel's edge network drops `Set-Cookie` on responses that flow
through the `rewrites()` proxy. Known limitation — rebrand
documentation around cache-poisoning prevention.

### Fix

For any login flow where the cookie must reach the browser, hit the
backend **cross-origin** (axios baseURL) instead of via a Vercel
rewrite. CORS is already configured in `apps/api` via
`ALLOWED_ORIGINS`.

### Detection rule

Whenever you add a `rewrites()` block in `next.config.js`, document
which response headers MUST reach the browser. Cookies are the most
common casualty. If the rewrite is needed for cross-origin avoidance
but you also need cookies — go cross-origin instead, don't proxy.

---

## 2026-06-29 — FastAPI: `return JSONResponse(...)` shadows injected `response`

### Symptom

Handler signature is `async def handler(req, response: Response, ...)`.
The handler calls `_set_refresh_cookie(response, refresh_token)`. The
browser receives a 200 response, but **no Set-Cookie header**.

### Root cause

When the handler explicitly returns a `JSONResponse(content=...)`,
FastAPI uses that return value as the final response and **discards
the injected `response: Response` parameter** — including any
headers (like `Set-Cookie`) that were set on it. The injected
`response` is only kept when the handler returns a pydantic model
or a plain dict (which FastAPI then wraps using the injected
response, preserving its headers).

### Fix

Return a plain dict or pydantic model, not an explicit JSONResponse:

```python
# ✅ correct — injected response's headers (Set-Cookie) survive
return {"verified": True, "access_token": ..., "refresh_token": ...}

# ❌ broken — Set-Cookie on the injected response is discarded
return JSONResponse(content={"verified": True, ...})
```

### Detection rule

When reviewing a PR that adds a new FastAPI handler:

```bash
rg -n "return JSONResponse" apps/api/app
```

Every hit should be either (a) an error path that intentionally
builds a custom error response, or (b) flagged for migration to
`return dict`. Login success paths are **never** a legitimate place
for explicit `JSONResponse`.

---

## How to add a new entry

When you find yourself typing "let me try a different fix" — STOP.

1. Write down the failed attempt and what it actually changed.
2. Ask: am I fixing the symptom or the cause?
3. If you're about to guess a second time, run
   `systematic-debugging` Phase 1 (read errors, reproduce, check
   recent changes, gather evidence across component boundaries).
4. After three failed fix attempts against the same symptom, STOP
   and question the architecture (per the Iron Law in
   `~/.mavis/agents/mavis/skills/systematic-debugging/SKILL.md`).
5. Once you find the real fix, document it here **in this exact
   format**: Symptom → Root Cause → Fix → Detection Rule.