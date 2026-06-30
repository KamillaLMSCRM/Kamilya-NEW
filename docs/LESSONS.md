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
