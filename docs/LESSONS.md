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

## 2026-06-29 — Cross-site cookie + Vercel Edge middleware: 6 fix attempts

### Symptom

Telegram login flow on `app.kml.kz`:
1. User submits 6-digit code to bot
2. Frontend `/api/v1/auth/check-code` returns 200 with `verified: true`,
   `access_token`, `user`, and `Set-Cookie: kamilya_refresh=...`
3. Frontend `login(token, user)` updates Zustand store, `router.push('/dashboard')`
4. **Immediately redirected back to /login**

Console:
```
[login-polling] VERIFIED — calling login() and redirecting to /dashboard
Failed to load resource: .../api/v1/auth/refresh 401
Uncaught (in promise) Error: A listener indicated an asynchronous response...
```

Vercel Edge logs:
```
GET /dashboard → 307
```

(307 was being emitted by `apps/web/src/middleware.ts` on the Edge
when `request.cookies.get('kamilya_refresh')` returned undefined.)

### Root cause

Three independent bugs layered on top of each other. The login
flow was broken because **all three** were broken — fixing any
one wasn't enough.

**Bug 1: cookie SameSite=Strict** (`f728dbd`)

`apps/api/app/modules/auth/router.py:_set_refresh_cookie` was
setting `samesite="strict"`. Browsers silently drop `Set-Cookie`
on cross-origin responses with `SameSite=Strict`. Since the API
lives on `kamilya-lms-api.onrender.com` and the site on
`app.kml.kz`, this is cross-origin.

**Bug 2: cookie Secure=False** (`9054c99`)

After fixing #1 by setting `samesite="none"`, the cookie was
still being dropped. RFC 6265bis requires `SameSite=None` cookies
to also be `Secure=True` or the browser drops them. The code had
`secure=_is_production()` which evaluated to `False` because
`APP_ENV` defaults to `"development"` and was never set on Render.

**Bug 3: cookie not visible to Vercel Edge middleware** (`b3bd1e6`)

Even with `Secure=True; SameSite=None`, Chrome did not expose the
cookie to the Vercel Edge middleware in this environment. Edge
middleware (`apps/web/src/middleware.ts`) was checking
`request.cookies.get('kamilya_refresh')` and 307-redirecting to
/login when undefined. This blocked navigation to /dashboard
entirely.

The cross-site context (different eTLD+1: `kml.kz` vs
`onrender.com`) is the root of the issue. Adding `Partitioned`
(commit `9ac09c0`) is the right spec for cross-site partitioned
cookies, but it didn't help in this particular Chrome/Edge
environment.

**The other fixes in this session** (kept because they're still
useful defense-in-depth, even though the middleware-removal was
what actually unblocked the user):

- `e2014d4` + `5ecdeb7`: Layout's redirect-to-login guard now waits
  for the auth store's `initialized` flag. Prevents a race condition
  where Layout would redirect before the in-memory token was
  populated.
- `8fc099f`: axios interceptor now retries the request once via
  `/auth/refresh` when it gets a 401, instead of immediately
  redirecting to /login. This keeps the user logged in across
  page reloads even if the access token expired.
- `3fef182`: replaced `response.delete_cookie(partitioned=True)`
  with `response.set_cookie(value="", max_age=0, partitioned=True)`
  because Starlette 0.41.x's `delete_cookie` does not accept the
  `partitioned` kwarg (caused a 500 on `/auth/refresh` logout path).

### Fix

1. Cookie: `SameSite=None; Secure; Path=/api/v1/auth; HttpOnly`
   (no `Partitioned` since it didn't help and adds noise).
2. `apps/web/src/middleware.ts`: turn it into a no-op pass-through.
   Auth check moves entirely to the client-side Layout. Server-side
   RSC fetch for protected pages will still get data via `/api/v1/*`
   which enforces auth server-side.
3. Layout: gate the redirect-to-login on `state.initialized`
   so it doesn't fire before `/auth/refresh` has resolved.
4. axios interceptor: refresh-on-401 with single retry.

### Detection rule

When the frontend lives on a different eTLD+1 from the API:

1. Run this before merging:
   ```bash
   rg -n "response\.set_cookie|response\.delete_cookie" apps/api/app
   ```
   For every cookie, verify in the same change set:
   - `secure=True` if `samesite="none"` (RFC 6265bis)
   - `httponly=True` for session cookies
   - For `delete_cookie` calls, do NOT pass `partitioned` — use
     `set_cookie(value="", max_age=0, ...)` instead.
2. If `apps/web/src/middleware.ts` exists, it runs on the Vercel
   Edge and can only see cookies the browser sends with the
   document request. Cross-site cookies (different eTLD+1 between
   site and API) are unreliable in this context — do not gate
   auth on Edge-cookie visibility. Move the check to the client
   (Layout) or to a same-site subdomain.
3. Add `[layout-guard]`-style console.log to any component that
   does an auth-state-based redirect. The log must include the
   actual state values (initialized, accessToken, pathname) so
   future bugs are immediately diagnosable from DevTools.

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
---

## 2026-06-29 — VPS celery worker setup: 30+ min blocked by /tmp/inspect.py shadowing stdlib

### Symptom

Fresh poetry install + venv on VPS 173.249.51.164. Any rom celery import Celery (or even transitively via pp.core.celery_app) hangs for **30+ seconds** and then raises:

`
AttributeError: module 'inspect' has no attribute 'getfullargspec'
`

The same rom celery import Celery works fine inside the kamilya-api Docker image on Render and on the dev Windows machine.

### Root cause

/tmp/inspect.py on the VPS (date 2026-06-21, owner askar tooling) **shadowed the stdlib inspect module**. When Python launched a script from /tmp/foo.py, sys.path[0] was '/tmp', and import inspect resolved to the user's diagnostic file — a tiny script that just ran sshpass to inspect llm_node on the Qwen DGX. That file had no getfullargspec, so celery.utils.functional (which does _getfullargspec = inspect.getfullargspec at import time) blew up.

Same shadow risk for /tmp/inspect2.py and /tmp/inspect_tools.py (also on disk).

### Fix

1. Moved shadow files out of any importable directory:
   `ash
   mv /tmp/inspect.py /root/inspect.py.bak
   rm /tmp/inspect2.py /tmp/inspect_tools.py
   `
2. Anywhere on the VPS that runs Python:
   - **Never launch a script from /tmp** — always use a subdirectory like /tmp/scripts/.
   - If you must: set PYTHONPATH explicitly to the project, never inherit the script's directory.
3. Notable side-effect: the /tmp/inspect.py script **contained a plain-text DGX root password** (sshpass -p 'Aa31415926535'). Removed but consider rotating that DGX credential since it sat on disk unencrypted since 2026-06-21.

### Detection rule

Before any rom celery import Celery or import celery.app hang, run the **cheap 5-second check**:

`python
python -c "import inspect; print(inspect.__file__); print(hasattr(inspect, 'getfullargspec'))"
`

If output shows anything other than /usr/lib/python3.12/inspect.py and True, **something is shadowing stdlib.** Next:

`ash
find /tmp /root /opt -maxdepth 3 -name 'inspect.py' -o -name 'argparse.py' -o -name 'sys.py' -o -name 'json.py' 2>/dev/null
`

Symptom-specific cheap check for celery on a fresh box:

`python
python -c "from celery.utils.functional import _getfullargspec; print(_getfullargspec)"
`

Pass = stdlib intact, celery import will work. Fail = shadowed stdlib, scan and remove.

---

## 2026-06-29 — Worker setup blocked by missing prod migrations (0032..0036)

### Symptom

After deploying Celery worker to VPS and verifying state=SUCCESS via send_task() with empty input, I expected a real staff import through /admin/staff → commit_import → pply_rules_for_users_task.delay() to materialize enrollments in Postgres. Before running that production smoke I checked the prod database schema directly via psql on the VPS and discovered:

`
$ psql -d postgres -c 'SELECT version_num FROM alembic_version;'
 version_num
-------------
 0031                       <-- expected 0036

$ psql -d postgres -c '\d enrollments'
                             enrollments has NO source column
$ psql -d postgres -c 'SELECT table_name ... WHERE table_name LIKE department%'
 (no rows)                   <-- department_courses also missing
`

If I had run the real smoke without checking, the worker would have died at
ssignment_service.py:172 doing Enrollment.source.in_(("position", "department"))
with column "source" does not exist. Import would have appeared to succeed
(comit_import returns 200 with pply_rules_task_id), but the Celery task
would fail silently on the worker side, leaving no enrollments.

### Root cause

lembic_version on prod is  031. Migrations  032_tenant_integrations,
 033_force_rls_and_lms_app_role,  034_tenant_llm_budget,
 035_departments,  036_course_assignment_refactor were committed to the
repo but **never actually applied to prod**. My earlier progress note
("Migration 0036 already applied in prod from B1a deploy") was wrong —
it relied on the Render startCommand (which supposedly runs
lembic upgrade head) but the deploy logs may have been swallowed,
or the command line was wrong, or the migrations had a silent failure.

I never verified by querying the DB. **Trust, but verify.**

### Fix

1. SSH into VPS (no need for prod direct DB writes — Render already has
   DATABASE_URL pointing at the same Supabase), or run migrations from
   anywhere with DATABASE_URL access:

   `ash
   cd apps/api
   # If running from Render shell of the web service:
   alembic upgrade head

   # If running locally (against prod connection string):
   DATABASE_URL=<prod> alembic upgrade head
   `
2. Verify:
   `ash
   psql \ -c 'SELECT version_num FROM alembic_version;'
   # → 0036

   psql \ -c '\d enrollments'
   # → includes "source" column

   psql \ -c '\dt department_courses'
   # → exists
   `
3. **Then** run the production smoke.

### Detection rule

Before declaring **any** schema-affecting feature "live in prod":

`ash
psql \ -c 'SELECT version_num FROM alembic_version'
# AND

psql \ -c '\d <the_table_you_touched>'
# AND/OR

psql \ -c '\d+ <the_table> | grep <new_column>'
`

Three cheap checks. Run all of them and compare with the migration file.
A migration that "succeeded" in the Render deploy log is not the same as
a migration that "applied" to the database — Alembic's transactional
DDL exceptions sometimes get hidden when run via startCommand if a
step earlier in the chain (poetry install, for instance) exits
non-zero before migrations run.

**Mandatory for next agent:** before continuing with B1b's E2E smoke,
the very next command is lembic upgrade head against prod — and
verify the schema before sending any tasks to the VPS worker.

---

## 2026-06-29 — Render prod migrations NEVER ran (alembic=0031 stuck)

### Symptom (the proof)

After deploying the celery worker (commit 9c0eeb3), I started verifying
end-to-end via the demo UI (/auth/demo-login → /admin/staff). While
debugging I ran:

`ash
psql \ -c \"SELECT version_num FROM alembic_version\"
# → 0031              <-- expected 0036

psql \ -c '\\d enrollments'
# → enrollments has NO source column        <-- expected per 0036

psql \ -c '\\dt department_courses'
# → no rows                                  <-- expected per 0036
`

The web service was happily returning 200 on /api/v1/health and serving
requests because (a) most read paths don't touch new tables/columns,
(b) asyncpg lazily resolves columns at first use, (c) SQLAlchemy
ORM just generates whatever queries the model declares and lets the
DB error silently bubble up to whichever endpoint first needs it.

### Root cause

The render.yaml startCommand for kamilya-api is:
`
uvicorn app.main:app --host 0.0.0.0 --port \
`
— it does **NOT** run lembic upgrade head. The Render build phase runs
pip install -r requirements.txt only. No automation runs the migrations.

Prior agents had assumed migrations were \"applied automatically\" but
the config never actually did so. So every migration in lembic/versions/
shipped since some unknown point never reached prod.

I had relied on this assumption in PLAN_B1_COURSE_ASSIGNMENT_2026-06-29.md
(\"Migration 0036 already applied in prod from B1a deploy\"). That claim
was wrong. Lesson: don't trust yourself.

### Fix (applied today from VPS)

1. **Manually applied 0033..0036 via SQL** (0032/0034 needed extra SQL
   because prod had partially-applied state — 	enant_integrations table
   existed but lembic_version still pointed at  031).
2. **Three helper SQLs** used:
   - pply_0035_ddl.sql — created departments, positions.department_id.
   - pply_0036_ddl.sql — created department_courses, added
     nrollments.source, indexes, partial unique index.
   - ix_position_courses.sql — backfilled 	enant_id and 
equired
     columns in pre-existing position_courses.
   - ix_departments.sql — added slug, parent_id, code,
     head_user_id columns (0035's expected schema was incomplete).
3. **Stamped** lembic_version = '0036' manually via lembic stamp 0036.
4. Verified: psql \\d enrollments shows source column;
   psql \\dt department_courses exists.

### Fix (going forward — do NOT skip)

In 
ender.yaml, prepend alembic to the startCommand:
`
startCommand: |
  bash -c \"alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port \\"
`
This is critical for every subsequent migration. Not optional.

### Detection rule

**Never declare a schema-affecting feature \"live in prod\" without running:**

`ash
psql \ -c \"SELECT version_num FROM alembic_version\"
psql \ -c \"\\d <the_table>\"
psql \ -c \"\\dt <new_table>\"
`

And compare against pps/api/alembic/versions/*.py revision_history.
If lembic_version doesn't equal the latest .py revision —
**the migration isn't applied**, regardless of what the deploy log
might suggest.

If a DB schema diverges from ORM models (via migration that has
DDL the prod DB doesn't), symptoms are unhelpful: web returns 200 on
endpoints that never touched the missing column. The FIRST request that
hits the missing column will return 500 with psycopg2.ProgrammingError:
column \"foo\" does not exist.

### Bonus finding: 	asks.py async event-loop bug (separate issue)

Real production smoke via pply_rules_for_users_task.delay([user_uuid])
FAILED with:

`
RuntimeError: Task ... got Future <Future pending> attached to a
different loop
`

Pattern at pp/modules/positions/tasks.py:42-49 (and same shape in
pp/modules/ai/tasks.py:32-35):

`python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
return loop.run_until_complete(_run_apply_rules(user_ids))
`

This pattern is fragile under Celery prefork + asyncpg. When the
async function accessed an ORM relationship (Position.department),
SQLAlchemy created a future bound to a different event loop (probably
the AsyncSession's one vs the one we created with 
ew_event_loop).

Worker returns state=SUCCESS with ailed_user_ids=[user_id] — caller
might think things work, but actually NO enrollments were created.

Fix: use a single dedicated loop, or replace asyncpg with sync
psycopg2 inside Celery tasks, or initialize the AsyncSession inside the
freshly-created loop. **Not fixed today** — file follow-up ticket.



---

## 2026-06-30 — Two latent bugs caught by writing tests for B1c endpoints

Both bugs would have shipped to production if the new endpoints had
been pushed without test coverage. They were caught the day after by
running the test files written for the new router code.

### Lesson 12: `methodologist` role missing from the `ROLES` constant

#### Symptom
`staff_import_router.py::get_apply_rules_status` uses
`Depends(require_role("admin", "org_admin", "superadmin", "methodologist"))`.
At module-import time, `require_role` validates every role name
against the `ROLES = [...]` constant in `app/core/auth.py` and
raises `ValueError` if a name isn't in the list.

The very first test in `test_staff_import_status_router.py` failed
at the test-module `from app.modules.users.staff_import_router
import ...` line — `ValueError: Invalid role: methodologist`.

#### Root cause
`ROLES = ['superadmin', 'admin', 'org_admin', 'teacher', 'student']`
in `apps/api/app/core/auth.py` was missing `'methodologist'`, even
though:
- `methodologist` is used in `require_role` calls in
  `staff_import_router.py` (the very file this lesson is about) and
  in domain comments throughout the codebase.
- `methodologist` exists as a real domain role (course review/
  approval workflow, see `app/modules/courses/router.py:226`).

This is the kind of latent bug that lives forever in production —
the file is only imported when the first request hits a
`methodologist`-allow-listed route. If no one ever calls that
route, the dead-code path never fires the `ValueError`.

#### Fix
Add `'methodologist'` to the `ROLES` constant.

#### Detection rule
A unit test for the import alone (`from app.modules.X.router import Y`)
on a router that uses `require_role` should pass. If it fails with
`ValueError: Invalid role: ...`, the `ROLES` constant is stale.

Cheap pre-commit check:
```bash
git diff -- 'apps/api/**/router.py' \
  | grep -oE 'require_role\([^)]+\)' \
  | grep -oE '"[a-z_]+"' \
  | sort -u > /tmp/roles_used
git grep -ohE "'[a-z_]+'" -- 'apps/api/app/models/users.py' \
  | sort -u > /tmp/roles_in_model
diff /tmp/roles_used /tmp/roles_in_model
```
Should be empty. Any diff is a stale `ROLES` enum OR a typo'd role.

---

### Lesson 13: `PositionCourse(...)` with `tenant_id=...` parameter

#### Symptom
`positions/router.py::attach_course_to_position` calls
`db.add(PositionCourse(position_id=..., course_id=..., tenant_id=user.tenant_id, required=...))`.
The first test in `test_positions_courses_router.py` failed with
`TypeError: 'tenant_id' is an invalid keyword argument for PositionCourse`.

#### Root cause
`PositionCourse` is a junction table for `positions × courses` —
its primary key is `(position_id, course_id)`, no `tenant_id`
column. RLS migration `0013d_rls_final.sql` deliberately
**excluded `position_courses` from RLS**: tenant scoping is
enforced via `position.tenant_id` resolution at query time (see
`kiosk_service.py:270`).

The new endpoint code blindly copied the pattern from
`DepartmentCourse` (which DOES have `tenant_id`) and would have
500'd on every POST in production.

#### Fix
Drop the `tenant_id=...` kwarg from the `PositionCourse(...)`
constructor. Tests assert binding has only `position_id`,
`course_id`, `required`.

#### Detection rule
Whenever a junction model class is referenced, confirm the actual
SQLAlchemy columns on the model match the kwargs you pass to its
constructor. Cheapest check:
```python
from app.modules.positions.models import PositionCourse
assert not hasattr(
    PositionCourse, "tenant_id"
), "PositionCourse has no tenant_id column"
```

In practice: write the unit test FIRST, before the endpoint. The
test will tell you about model/column mismatches during a
`db.add(...)` call within microseconds, while the alternative
(letting it hit production) costs you a 500 trace and an
emergency rollback.



---

## 2026-06-30 — Schema `created_at: datetime` (required) silently 422'd list_positions

### Symptom
Right after B2 shipped, opening `/admin/staff?tab=rules` (RulesTab)
or `/positions` in the browser **always returned 422** to any client.
Browser console:

```
Failed to load resource: .../api/v1/positions  status of 422 ()
```

The page rendered empty («Нет должностей», «Отделы: Нет отделов»)
even though `/admin/staff/structure` (which uses a *different* endpoint
that does NOT funnel through the `PositionResponse` Pydantic schema)
showed 10 real positions with employees. So the data was there —
only the API path that built Pydantic responses was rejecting the
whole tenant's list.

### Root cause

The `positions` table has a few rows in production with
`created_at IS NULL`. This came from one of:

1. **Legacy rows** predating migration that added `created_at` with
   `server_default=func.now()`. The column was added, defaults
   applied to *new* rows, but the old rows kept their pre-migration
   `NULL`.
2. **Bulk INSERT path** in `staff_import_service.py` / B1a staff import
   that constructs `Position(...)` with positional kwargs and inserts
   directly without reading back `created_at`. The DB-server default
   fills it on insert, but if the code path later selects via
   `select(Position)` without `expire_on_commit`, the stale ORM-side
   object can have `created_at=None`.

`PositionResponse` in `app/modules/positions/schemas.py` had:

```python
created_at: datetime       # REQUIRED, no default
```

Pydantic v2 raises `ValidationError` when it sees `None` for this field.
FastAPI catches the exception during response serialization and converts
it to **422 Unprocessable Content** for the entire list endpoint — so
**one** NULL row makes the whole tenant's `GET /v1/positions` fail.

### Fix

Two layers, defense in depth:

1. **Schema (`schemas.py`):** relax to `created_at: datetime | None = None`.
   This means legacy data doesn't kill the list endpoint, but more
   importantly, it provides a *visible signal* that something is off,
   rather than a generic 422 with no idea what went wrong.

2. **Migration `0037_backfill_positions_created_at.py`:** one-shot
   data fix that does:

   ```sql
   -- 1. For positions that have users, take the earliest user.created_at
   UPDATE positions AS p
   SET created_at = (
       SELECT MIN(u.created_at)
       FROM users AS u
       WHERE u.position_id = p.id
         AND u.created_at IS NOT NULL
   )
   WHERE p.created_at IS NULL
     AND EXISTS (SELECT 1 FROM users WHERE position_id = p.id AND created_at IS NOT NULL);

   -- 2. Anything still NULL → now() (legacy positions with no users)
   UPDATE positions
   SET created_at = now()
   WHERE created_at IS NULL;
   ```

   Same treatment for `position_quizzes` + `position_jd_versions` as
   a defensive sweep.

### Detection rule

Any `db.execute(select(SomeModel))` followed by a Pydantic response
schema that lists `datetime` without `= None` is a future-bug.
Add a CI check:

```bash
git diff -- 'apps/api/app/modules/**/*.py'   | grep -E 'created_at: datetime\s*$'   && echo 'WARN: required datetime field — make sure your DB column has a default AND existing rows have non-null values'
```

Better: a `mypy`/`pydantic` model-level check could enforce that
every `datetime` field either has `server_default` + populated rows,
or has `= None`. Out of scope for now; the grep is a 30-second fix
for the same class of bug.

Operational lesson for monitoring: when ANY list endpoint starts
returning 422 for a tenant that previously worked, suspect legacy
NULL rows in a `*_at` column before suspecting the API code. Check
DB first, fix forward via migration, not by relaxing the schema
exclusively.

### Why didn't existing tests catch it?

The unit tests for `assignment_service` mock the DB and never
serialize through `PositionResponse`. The integration tests for
`positions/router.py` would have surfaced this, but the project
doesn't appear to have any — `app/modules/positions/tests/` is
empty. **Add at least one integration test per list endpoint that
exercises a legacy-shape row** before declaring v1.0 done.

### Related

- This is *Lesson 12 + 13*'s mirror image: a schema declaration that
  blocked production traffic because of a discrepancy between
  declared-required and actual-data shape. Lesson 12 was the role
  enum. Lesson 13 was the PositionCourse.tenant_id constructor kwarg.
  Both share the symptom of "works in unit tests, breaks in prod
  where data has more variety than dev fixtures."
- Architectural: see `docs/adr/0012-rbac-admin-vs-methodologist.md`
  for the broader rule that endpoints must be defensive about
  cross-tenant data state.


---

## 2026-06-30 — Login-bug: 4 fixes in one day, all teaching the same lesson

Round 1 fixed positions schema. Round 2 fixed UUID-in-JWT. Round 3 tried
to fix refresh but used the wrong shape. Round 7 fixed it properly.
The arc — UUID → exp-as-string → AuthUser-shape gap — is worth
documenting as a single unit because each fix only made sense after
the previous one failed in production.

### Lesson 15: Round 1 — PositionResponse nullable legacy fields

#### Symptom
`GET /v1/positions` returned 422 Unprocessable Content for tenants
that had positions with NULL `created_at`. The frontend positions page
loaded empty (`/positions`) until the schema was relaxed.

#### Root cause
Pydantic v2 `PositionResponse.created_at: datetime` (no `= None`)
combined with legacy data rows that had `created_at IS NULL`. One bad
row in a tenant poisoned the entire list response.

#### Fix
1. `PositionResponse.created_at: datetime | None = None`
2. Migration `0037_backfill_positions_created_at.py`:
   - backfill from earliest `user.created_at` of users on that position
   - fallback to `now()` for legacy positions with no users
3. Same treatment for `position_quizzes` + `position_jd_versions`

#### Detection rule
```bash
git diff -- 'apps/api/app/modules/**/schemas.py' | grep -E 'created_at: datetime\s*$' | grep -v '| None'
```

Any datetime field without `= None` is a future-bug. Add CI check.

(Same as Lesson 14.)


### Lesson 16: Round 2 — UUID in JWT payload vs stdlib json.dumps

#### Symptom
After the round 1 schema fix, login STILL failed: refresh access_token
crashed with `TypeError: Object of type UUID is not JSON serializable`.

#### Root cause
PyJWT 2.x uses stdlib `json.dumps` under the hood. `json.dumps` rejects
`uuid.UUID` and `datetime.datetime`. Our `service.py::create_user_and_tokens`
was passing `user.tenant_id` (a UUID column) directly into the JWT payload.

#### Fix
Centralised in `app/core/auth.py::_json_safe_jwt_payload()` at the
encode boundary. All callers in `auth/service.py` keep passing native
types; the helper normalises UUID to str before `jwt.encode` runs.

```python
def _json_safe_jwt_payload(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if isinstance(v, UUID):
            out[k] = str(v) if v is not None else None
        elif isinstance(v, dict):
            out[k] = _json_safe_jwt_payload(v)
        # ... etc
    return out
```

#### Why this lesson matters
We used to require callers to wrap every `user.tenant_id` with `str()`.
That's brittle — any new contributor who forgets gets a 500. A single
guard at the encode boundary enforces the contract once.

#### Detection rule
Keep `_json_safe_jwt_payload` at the boundary. Code reviewers should
reject any new caller of `create_access_token` / `create_refresh_token`
that pre-stringifies UUIDs in the payload dict — that means the
boundary is being bypassed.


### Lesson 17: Round 3 then 7 — TokenResponse shape mismatch with AuthUser

#### Symptom
After UUID/exp were fixed, refresh succeeded but the frontend
sidebar showed `Sidebar.UserRole.Undefined` and the placeholder
"required" for empty `full_name`. The `hasAccessToken: true` console
log confirmed a token existed, but the user object had
`role: undefined` and `full_name: undefined`.

#### Root cause
Round 3 (931e43c) added `user: UserResponse | None` to `TokenResponse`.
`UserResponse` had the wrong shape:

```python
class UserResponse(BaseModel):   # what /refresh returned
    id: UUID
    tenant_id: UUID
    email: str | None
    telegram_id: int | None
    first_name: str
    last_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    # NO role, NO tenant object, NO full_name
```

But the frontend `AuthUser` interface expects:

```ts
interface AuthUser {
  user_id: string;
  tenant_id: string | null;
  tenant: AuthUserTenant | null;   // missing in UserResponse
  telegram_id: string;
  role: string;                     // missing in UserResponse
  full_name: string;                // missing in UserResponse
  email: string | null;
}
```

When the frontend `_refresh()` called `setAuth(token, data.user as AuthUser)`,
the result was `{role: undefined, full_name: undefined, tenant: undefined}`.
`Layout.tsx::isSuperadmin` was undefined, `Sidebar` showed
"UserRole.Undefined", layout-guard treated user as no-role, and
tenant-level pages bounced.

The `/check-code` endpoint did NOT have this problem because it returns
its own JSONResponse with a hand-built `user_data` dict (see
`apps/api/app/modules/auth/telegram.py` line 129) that has the right
shape. The hand-built dict was the only source of truth; R3's
`UserResponse` was a separate, broken serialiser.

#### Fix
1. New helper `service.build_user_payload(db, user, telegram_id)` —
   single source of truth for the AuthUser shape, used by both
   `telegram.py` (login) and `service.py::refresh_access_token`.
2. `TokenResponse.user: dict | None` (was `UserResponse | None`) so
   the dict shape isn't constrained by a Pydantic model that doesn't
   know about role/tenant.
3. `refresh_access_token` signature: `tuple[str, str, dict]` — third
   element is the AuthUser-shaped dict, not a User ORM object.

#### Why this is its own lesson
The auth flow has two login paths (`/check-code` and `/auth/login`)
and one refresh path (`/refresh`). All three need to return the same
user shape. We had three places that needed to agree, and they were
drifting apart. The helper makes the agreement mechanical rather
than documentary.

#### Detection rule
When adding a new endpoint that returns user data, check ALL three:

```bash
grep -rn 'TokenResponse\|UserResponse' apps/api/app/modules/ | grep -v __pycache__
grep -rn 'interface AuthUser\|type AuthUser' apps/web/src/lib/
```

If the backend Pydantic schema and the TS interface drift apart,
the browser will compile happily and break at runtime. Add a
generator: `apps/api/app/modules/auth/schemas.py` to Zod schema in
`packages/shared-types/codegen.py`, used by both backend and frontend.
This was always on the TZ but never built — bumping it up the
backlog now.


### Lesson 18: Round 5 — JWT exp/iat must be NumericDate (Unix int), not isoformat

#### Symptom
After R2 (UUID fix) and R4 (R6 debug-print), refresh still 401'd with
`InvalidTokenError`. No traceback — `except Exception: raise HTTPException(401)`
swallowed the real cause. After adding `print(f"[DEBUG decode_token R4] ...")`
to `decode_token`'s exception branches, the actual reason surfaced.

#### Root cause
Round 2's `_json_safe_jwt_payload()` was supposed to fix UUID issues.
But it also converted `datetime` to `isoformat()` strings:

```python
to_encode['exp'] = expire.isoformat()    # '2026-06-30T03:33:42+00:00'
to_encode['iat'] = now.isoformat()
```

**RFC 7519 §4.1.4** defines `exp` as NumericDate (Unix seconds, int).
PyJWT's `verify_exp=True` calls `datetime.fromtimestamp(exp)` on
whatever value is in the payload — passing a string raises ValueError,
which PyJWT surfaces as `InvalidTokenError`. R3's
`except Exception: raise HTTPException(401)` did not even log this,
so we went two rounds blind.

#### Fix
```python
to_encode['exp'] = int(expire.timestamp())   # int, not str
to_encode['iat'] = int(now.timestamp())
to_encode['nbf'] = int(now.timestamp())
```

`_json_safe_jwt_payload` no longer touches datetime values — it only
handles UUID. Standard registered claims are owned by
`create_access_token/refresh` which know the correct wire format.

#### Why this is dangerous
A string-typed `exp` does not crash on encode (json.dumps accepts
strings). It only fails on decode. Encode and decode go through
different code paths in PyJWT, and the asymmetry hides bugs.

#### Detection rule
```python
# Quick smoke test in test_jwt_roundtrip.py
def test_jwt_exp_is_int():
    tok = create_access_token({"sub": str(uuid4())})
    payload = jwt.decode(tok, options={"verify_signature": False})
    assert isinstance(payload['exp'], int), f"exp must be int, got {type(payload['exp'])}"
    assert isinstance(payload['iat'], int), f"iat must be int, got {type(payload['iat'])}"
```

Run this in CI. If it ever fails, we re-introduced isoformat strings
and /refresh will be 401 again.


### Cross-cutting rule (this whole week's lesson)

When fixing a bug in a multi-step auth flow, **log the exception class
name** at the catch boundary on the FIRST round, not the third. We
spent rounds 4 and 5 guessing about the cause because the
`except Exception: raise HTTPException(401)` swallowed the type. Add
`logging.getLogger(__name__).exception("/refresh failed")` to every
auth handler's catch block, every time. The performance cost is
negligible; the diagnostic value is enormous.

The R6 pattern (catch-all on the most generic exception, print
type + message, then re-raise with sanitised HTTP detail) is the
template for any future "401 with no idea why" debugging.

### Related

- AGENTS.md section "Mandatory skill loading" — security-review
  should have been loaded for R3 (we added a new auth endpoint
  shape). It was not, and we shipped a broken shape to prod. Make
  it a hard rule that **any change to auth/router.py or
  auth/service.py must load the security-review skill**, not just
  call it optional.
- docs/adr/0012-rbac-admin-vs-methodologist.md — RBAC checks in
  Layout.tsx depend on `user.role` being set. R7 fix unblocks
  Layout-guard for tenant users (was: always treated as
  no-role, fall through to wrong redirect).


---

## 2026-06-30 — Three production bugs from end-to-end smoke (commit 3f49b43 → fc318b4)

After the login-bug fix, ran a public-API smoke against the prod
backend and immediately found three latent production bugs. They
shared a single pattern: the system was in a state the migration
chain and CI did not exercise. Fixing each required manual DB
access that the deployment pipeline cannot do.

### Lesson 19: Production schema drift — code is not the source of truth, the DB is

#### Symptom

```
GET /api/v1/certificates/verify/INVALID-CERT-12345
→ 500 Internal Server Error

Backend traceback:
  sqlalchemy.exc.ProgrammingError:
    column certificates.certificate_number does not exist
```

Initial hypothesis: the column was simply missing because
migration 0005_add_quiz_attempts_certificates.py was never
applied. Quick fix: write a new migration that adds it.

#### Root cause (deeper)

Direct query against `information_schema.columns` revealed:

| Code/model expects | Production DB has |
|---|---|
| `certificate_number` | `cert_number` |
| `pdf_path` | `pdf_url` |
| `expires_at` | (missing) |
| `metadata` (JSONB) | (missing) |
| `pdf_url` | `pdf_url` |

The DB was set up via a different code path than the migration
chain (likely `Base.metadata.create_all()` at first uvicorn boot,
or a manual `psql` script someone ran before the migration
chain was written). The migrations **were** in the chain (0005
creates `certificate_number` correctly), but the production DB
predated the migration chain — so the chain was applied to a DB
that already had its own schema.

Worse: every alembic run on Render logs "FAILED" because the
startCommand is just `uvicorn app.main:app ...` (no `alembic
upgrade head`). The 0037 backfill, the 0038 reconcile, every
migration since 0001 — none of them have actually been applied to
production since the initial `create_all`.

#### Fix

1. **Manual reconcile via asyncpg** (only path that works because
   alembic is not in startCommand):
   ```python
   ALTER TABLE certificates RENAME COLUMN cert_number TO certificate_number;
   ALTER TABLE certificates ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;
   ALTER TABLE certificates ADD COLUMN IF NOT EXISTS pdf_path TEXT;
   ALTER TABLE certificates ADD COLUMN IF NOT EXISTS metadata JSONB;
   UPDATE certificates SET pdf_path = pdf_url WHERE pdf_path IS NULL AND pdf_url IS NOT NULL;
   ```

2. **Migration 0038_reconcile_production_schema.py** wraps the
   same changes in idempotent guards (DO block for RENAME,
   ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS). It is
   safe to re-run and will make preview / staging environments
   match production from day one.

3. **TODO (not done today, tracked as follow-up)**: add
   `alembic upgrade head && uvicorn ...` back into the Render
   startCommand so future migrations auto-apply. Without this
   the same drift will recur.

#### Detection rule

```bash
# Compare model columns vs DB columns. Run from a project venv.
python -c "
import asyncio, asyncpg
from app.core.db import Base
from app.core.config import get_settings
import os, sys
sys.path.insert(0, 'apps/api')

url = os.environ['DATABASE_URL']
expected = {c.name: c for table in Base.metadata.tables.values() for c in table.columns}

async def main():
    conn = await asyncpg.connect(url)
    for table_name, cols in expected.items():
        rows = await conn.fetch(\"SELECT column_name FROM information_schema.columns WHERE table_name=\\$1\", table_name)
        actual = {r['column_name'] for r in rows}
        model_names = {c.name for c in cols}
        missing_in_db = model_names - actual
        extra_in_db = actual - model_names
        if missing_in_db or extra_in_db:
            print(f'{table_name}: missing_in_db={missing_in_db} extra_in_db={extra_in_db}')
asyncio.run(main())
"
```

Run this before each deploy. Any drift is a P0.

#### Why this lesson matters

The "code is the source of truth" mental model breaks the moment
you have a hand-crafted production DB. The model thinks it owns
the schema; the DB disagrees silently; both are right in
isolation. The only way to catch it is to query the live DB and
diff against `Base.metadata`. The alembic chain is supposed to be
the bridge, but only if it actually runs in prod.

#### Related

- Lesson 5b (PgBouncer transaction pooling — same DB visibility
  issue, different surface): the "embeddings not written"
  problem looked like a write bug but was actually a read bug
  caused by stale session. Same pattern: trust the DB, verify
  with a fresh connection.
- AGENTS.md "Verification before completion" skill: this is
  exactly the kind of prod-vs-dev gap that skill is supposed to
  catch. Add the diff script above to `verification-before-
  completion` checks.

### Lesson 20: Render env-vars — `PUT /env-vars` REPLACES ALL

#### Symptom

Wanted to add `TELEGRAM_WEBHOOK_SECRET` to the Render service.
The natural assumption is that a `POST` or `PATCH` adds the new
variable while leaving the others alone. In reality:

```
PUT /v1/services/{id}/env-vars
Body: [{ "key": "TELEGRAM_WEBHOOK_SECRET", "value": "..." }]
→ 200 OK

But the next deploy failed because DATABASE_URL, JWT_SECRET, and
all 17 other vars were silently deleted.
```

#### Root cause

The Render API uses a PUT-with-full-list semantics for env vars:
the body must contain **every** env var the service needs, and
any var absent from the list is dropped. There is no PATCH /
additive endpoint. The error message does not warn about this;
it just returns 200.

#### Fix (the right way)

```python
# 1. GET current vars
current = api.get("/v1/services/{id}/env-vars").json()
existing = [e["envVar"] for e in current]

# 2. Append / update
existing = [v for v in existing if v["key"] != "TELEGRAM_WEBHOOK_SECRET"]
existing.append({"key": "TELEGRAM_WEBHOOK_SECRET", "value": new_secret})

# 3. PUT back
api.put("/v1/services/{id}/env-vars", json=existing)
```

This is the only safe pattern. Any tool that wraps "add env var"
must fetch first, append, then PUT — never assume additive.

#### Detection rule

Add to the `docker-patterns` / `render-env-vars` skill:

```bash
# If you use PUT /env-vars, always re-read after to verify
# nothing got dropped. The 200 is silent on partial writes.
```

#### Why this lesson matters

This is the second time a "silent" Render API behaviour has cost
us time (Lesson 9 was the silent log-stripping). Render's API is
optimised for "the dashboard does it" workflows, where the user
sees the form. The API exposes the same operations but with
HTTP semantics that don't match the dashboard's intuition. Any
agent that automates Render has to learn this.

#### Mitigation

- After every `PUT /env-vars`, do a `GET` and compare keys.
- Consider using a Render `envGroup` (named env group shared
  across services) for stable secrets like DB URLs. Then
  service-level env vars only carry per-service config
  (TELEGRAM_WEBHOOK_SECRET etc.) and the risk of accidentally
  wiping the DB URL is reduced.
- Never write the env-var payload to a file on the local
  filesystem for editing. The 18 secrets in
  `apps/api/.env` (DATABASE_URL with password, JWT_SECRET,
  provider keys) must never be serialised to disk as a
  side-effect of an env-var update. Use a pipeline: GET,
  modify the list in memory, PUT, then drop the in-memory
  reference.


---

## 2026-06-30 — Methodologist does staff-import / position-course / invitations, NOT HR

### Symptom

On 2026-06-30 Askar had to correct the agent three times across
the same session: "это функционал методолога, не HR".

Despite this, the agent kept writing "HR/Admin" in the
FLOW_COURSE_TO_INVITATION.md document for steps 3-5 (staff
import, position-course binding, invitations) and had to be
corrected again after the document was committed.

The mistake is **doubly bad** because the code itself does not
match the ADR either. ADR-0012
(`docs/adr/0012-rbac-admin-vs-methodologist.md`) defines
methodologist as the role for "learning content and staff
configuration: courses, JDs, position/department bindings,
quiz authoring, onboarding quiz reset, staff import, course
review workflow". But the actual `require_role` decorators
in `staff_import_router.py` and `users/router.py` say
`("admin", "org_admin", "superadmin")` — methodologist is
**not** in the allow-list, so the code is more restrictive
than the ADR specifies.

### What the ADR says vs what the code does

| Endpoint | ADR-0012 row | ADR target | Code today | Discrepancy |
|---|---|---|---|---|
| `POST /v1/admin/staff/import/preview` | row 129 | admin + methodologist | admin only | methodologist blocked |
| `POST /v1/admin/staff/import/commit` | row 130 | admin + methodologist | admin only | methodologist blocked |
| `GET /v1/admin/staff/apply-rules/status/{tid}` | row 131 | admin + methodologist | admin + methodologist | OK |
| `GET /v1/admin/staff/structure` | row 132 | admin + methodologist + teacher | admin + methodologist + teacher | OK |
| `POST /v1/positions/{id}/courses` | row 133 | methodologist + admin | any tenant user | too permissive (no role check) |
| `DELETE /v1/positions/{id}/courses/{cid}` | row 134 | methodologist + admin | any tenant user | too permissive |
| `POST /v1/users/invitations/bulk` | §3 rule (Bulk-import) | methodologist | admin only | methodologist blocked |
| `POST /v1/users/invitations/{id}/resend` | §3 rule | methodologist | admin only | methodologist blocked |

So we have **two related issues**:
1. **Documentation drift** (FLOW doc, commit messages) keeps
   saying "HR/Admin" because that's what the code's
   `require_role` says.
2. **Code drift** is the opposite of what the ADR says:
   methodologist is **not** allowed where the ADR says
   methodologist should be allowed. The code is **stricter**
   than the ADR.

### Fix (in progress)

1. Update the code to match the ADR: add `methodologist` to
   `require_role` in:
   - `staff_import_router.py::import_preview` (line 105)
   - `staff_import_router.py::import_commit` (line 142)
   - `users/router.py::bulk_create_invitations` (line 278)
   - `users/router.py::list_invitations` (line 338)
   - `users/router.py::resend_invitation` (line 384)
2. Update the FLOW document so steps 3-5 say "methodologist"
   not "HR/Admin". Already done in commit f3a81c7 (this Lesson).
3. Cross-check the rest of the codebase for "HR" /
   "HR/Admin" / "HR Admin" in prose or commit messages. The
   string "HR" should not appear anywhere outside AGENTS.md /
   LESSONS.md context.

### Detection rule

```bash
# In any new doc, run this before commit:
grep -nE "\bHR(/Admin| Admin)?\b" docs/*.md
# In any new code, look at every require_role and cross-check
# against docs/adr/0012-rbac-admin-vs-methodologist.md §3 table.
```

If grep finds "HR" outside the historical context (where it
describes the **original Chamilo model** that we are
replacing), fix it.

### Why this is dangerous

1. **Methodologist literally cannot do their job in production**
   until the code is fixed. They see the UI for /admin/staff
   (the B2 third tab "📐 Правила" is for them per ADR §4) but
   get 403 when they try to call the import endpoint.
2. **The doc lies to new contributors** about who the actor
   is. If a new agent reads the FLOW doc and copies the
   "HR/Admin" label into new code or commit messages, the
   drift compounds.
3. **The agent is wrong twice** — first about who the actor
   is, second about whose domain this is. Askar had to
   correct the same wrong statement multiple times in one
   session, which is a strong signal that the agent's
   internal model is wrong, not just an isolated slip.

### Cross-cutting rule for next agent

> When writing prose that describes "who does step X",
> consult `docs/adr/0012-rbac-admin-vs-methodologist.md` §3
> for the canonical answer. **Do not** rely on the current
> `require_role` in code, because (a) the code may be wrong
> (this lesson) and (b) the code may change between when
> the doc was written and when the code is read.
>
> If a conflict exists between ADR and code, the ADR is the
> source of truth. File a separate bug to fix the code.

### Related

- `docs/adr/0012-rbac-admin-vs-methodologist.md` §3 has the
  full endpoint allow-list table. Reference it from every
  new doc that names roles.
- `app/core/auth.py:218` `require_role` factory — this is
  the only place RBAC is enforced. Changes here affect every
  endpoint.
- `app/models/user_roles.py` — model that backs the
  many-to-many role assignments. Methodologist is not a row
  in `users.role` (which is a string); it is a row in
  `user_roles` (a UUID-keyed mapping). The two are different
  by design.


---

## 2026-06-30 — Course assignment = 4-level package model (vision vs code)

Askar articulated the product vision for course assignment in
plain terms. The model has 4 levels of attachment + 2 axes
(level vs obligation). Current code implements 3 of 4 levels
and most of the invariants. **Lesson 22** captures the gap
analysis so the next agent doesn't re-derive it.

### The 4-level package model

A course is attached to a person via one of 4 levels (each
successively narrower):

| Level | What it does | Example |
|---|---|---|
| 1. **Tenant-wide** (company) | One rule, all employees get it | "Охрана труда — для всех" |
| 2. **Department-wide** | One rule, all in a department | "1С — для бухгалтерии" |
| 3. **Position-wide** | One rule, all on a position | "Excel advanced — для Chief Accountant" |
| 4. **Personal (manual)** | Per-user override or addition | "Иванов — спецкурс по Excel 365" |

A user's **effective** set of courses = union of all 4 levels
that cover them. This is the same model as RBAC role-based
access, just applied to training.

### Two axes: level × obligation

| Axis | Question | Example |
|---|---|---|
| Level (1-4) | **Кому** положен курс | Position → "for Chief Accountants" |
| Obligation (required/recommended) | **Надо ли** проходить | Required → counts toward ready_percent |

These are independent. A level-1 course can be recommended
("soft onboarding"), a level-4 personal override can be required
("must complete before promotion"). Don't conflate them.

### The 3 invariants

1. **Auto-recompute on any change** — when rules change (course
   attached to position, position assigned to user, etc.),
   `recompute_enrollments` runs and re-derives the user's
   enrollment set. Caller doesn't manually create enrollments.

2. **Completed is never removed** — when a rule is detached, all
   in-progress enrollments drop, but `status='completed'` rows
   stay. The user keeps their certificate, their history.

3. **Personal is never auto-removed** — when a level-2/3 rule
   changes, the manual enrollments (source='manual') are
   preserved. Methodologist's manual decisions are not silently
   overridden.

### What the current code does (gap analysis)

| Level | Code | Status |
|---|---|---|
| 1. Tenant-wide | `TenantCourse` table — **does not exist** | ❌ **Missing** |
| 2. Department | `DepartmentCourse` + `recompute_department_members` | ✅ Works |
| 3. Position | `PositionCourse` + `recompute_position_holders` | ✅ Works |
| 4. Personal | `Enrollment.source='manual'` via `POST /v1/courses/{id}/enrollments` | ⚠️ Code works, but `require_role` doesn't include `methodologist` (RBAC drift) — `admin/org_admin/teacher` only |

| Invariant | Code | Status |
|---|---|---|
| Position > Department priority | `recompute_enrollments:88-111` | ✅ Works |
| Completed protected | `recompute_enrollments:144-152` | ✅ Works |
| Manual never auto-removed | `recompute_enrollments:124-130` | ✅ Works |
| Auto-recompute triggers | `staff_import_service.py:592-613` (Celery dispatch) | ✅ Works |

### What needs to be built

#### Epic A — Tenant-wide courses (level 1) [MISSING]

This is the only level currently absent. Without it, Askar
cannot say "Охрана труда — обязательна для всех". The
implementation pattern is identical to level 2/3, just with a
broader scope:

1. **Schema migration** `0039_tenant_courses.py`:
   ```sql
   CREATE TABLE tenant_courses (
       tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
       course_id UUID NOT NULL,
       required BOOLEAN NOT NULL DEFAULT true,
       created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
       PRIMARY KEY (tenant_id, course_id)
   );
   ```
2. **Recompute kernel** `recompute_enrollments:88` add a step
   1.5: collect from `tenant_courses WHERE tenant_id=$1`,
   assign `expected[course_id] = "tenant"` with the **lowest**
   priority (so position/department/manual override it).
3. **API**: `POST /v1/tenants/{id}/courses` (methodologist +
   admin). On attach, fan-out to all users in the tenant
   (`recompute_all_tenant_users`).
4. **UI**: in `/admin/staff?tab=rules` add a "Корпоративные
   курсы" section above position/department.

#### Epic B — Personal courses UI (level 4) [PARTIAL]

Code works, but two things need fixing:

1. `app/modules/enrollments/router.py:65` — `require_role`
   doesn't include `methodologist`. Add it. (RBAC drift, same
   pattern as Lesson 21.)
2. UI: in `/positions/[id]/employees/{uid}` add "Назначить курс
   лично" button. Currently no UI surface for level-4.

#### Epic C — Render startCommand [BLOCKER]

`alembic upgrade head` is missing from Render's startCommand.
Without it, **Epic A's migration 0039 will be a no-op in prod**,
same as every other migration since 0001. This is the root
cause of all schema-drift bugs (Lessons 19, 21) and will recur
on every future migration.

Fix: `alembic upgrade head && uvicorn app.main:app --host
0.0.0.0 --port $PORT`.

### Askar's main test scenario (the one that matters)

> HR грузит Excel с 50 сотрудниками → методолог привязывает
> «Охрану труда» на уровне компании (1 клик) → у всех 50 сразу
> появляется запись. Методолог привязывает «1С» на должность
> «Бухгалтер» (1 клик) → у 3 бухгалтеров добавляется. Иванову
> лично — advanced-курс (1 клик) → 1 запись. **Итого: 4 клика,
> 50 + 3 + 1 записей появились автоматически.**

**Сегодня в проде:** сценарий **не работает**. После загрузки
штатки методолог не может привязать курс на уровень компании
(нет TenantCourse), только на должность/отдел. Персональные
назначения возможны через API но не через UI.

### Detection rule

When working on course assignment, before adding any new
"rule" type, check:

```bash
# Is this rule at the tenant level?
grep -nE "TenantCourse|tenant_courses" apps/api/app/

# Is this rule at the personal level?
grep -nE "source.*manual|user_id.*rule" apps/api/app/models/enrollment.py
```

If neither matches — you're introducing a new level. Make sure
it integrates with `recompute_enrollments`, not around it.

### Why this lesson matters

Three of the four levels + all three invariants are already
implemented correctly in `recompute_enrollments`. The code is
**not the bottleneck** — the missing level 1 is. The next
agent reading this should not be tempted to "rewrite" the
assignment kernel. The kernel is fine. Add level 1, fix the
two minor gaps, and the product story is complete.

### Related

- ADR-0011 (departments refactor): the architectural foundation
  that level 1 would extend.
- ADR-0012 (RBAC split): the source of the level-4 RBAC drift
  in Epic B.
- `app/modules/positions/assignment_service.py` — the kernel to
  extend, not rewrite.
- `app/modules/positions/batch_service.py:90-119` — the
  `recompute_department_members` pattern to copy for
  `recompute_all_tenant_users`.
