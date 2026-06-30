# Smoke-test production — 2026-06-30

After the 7-round login-bug fix (commits 4d6f5d3 → cca6c18) we
exercised the public API surface of the production backend
(`https://kamilya-lms-api.onrender.com`) to see what actually works
and what does not.

This is **not** a full UI smoke (login UI, navigation, etc.) — the
results below are from raw API calls made via
`Invoke-RestMethod` (PowerShell) against `/api/v1/openapi.json`
as the discovery source.

## Method

1. GET `/api/v1/openapi.json` to discover all 142 endpoints.
2. Authenticate via `POST /api/v1/auth/demo-login` (public, gives
   a JWT and a populated AuthUser payload). This is the only way to
   exercise authed endpoints without owning a tenant admin password.
3. For each endpoint we cared about, call it with the demo JWT and
   record the response status + body.

## What works

| Endpoint | Role | Status | Notes |
|---|---|---|---|
| `GET /health` | public | 200 OK | `{"status":"ok","app":"Kamilya LMS"}` |
| `GET /openapi.json` | public | 200 OK | 142 endpoints registered |
| `POST /auth/generate-code` | public | 200 OK | returns `code` + `expires_in` |
| `POST /auth/demo-login` | public | 200 OK | returns full AuthUser shape (role, tenant, full_name) |
| `GET /users/me` | authed | 200 OK | `user_id, tenant_id, role, telegram_id, is_active` populated |
| `GET /courses` | authed | 200 OK | 7 courses in demo tenant (3 published, 4 draft) |
| `GET /positions` | authed (admin) | 200 OK | 1 position ("Главный", 1 employee, 1 course) |
| `GET /enrollments/stats` | authed | 200 OK | `{"total":1,"completed":0}` |
| `GET /student/dashboard` | authed (student) | 200 OK | enrolled_courses=[], 0 progress |
| `GET /quizzes` | authed (admin) | 200 OK | 2 quizzes (pass_score 70 and 90) |
| `GET /ai/jobs` | authed | 200 OK | 8 historical jobs (4 completed, 4 failed) |
| `POST /telegram/webhook` | public | 200 OK | ⚠️ should be 404 without secret — see below |

## What does NOT work

### Bug 1: `GET /certificates/verify/{number}` returns 500

```
GET /api/v1/certificates/verify/INVALID-CERT-12345
→ 500 Internal Server Error
  "error": "internal_error",
  "message": "Internal server error"

Backend traceback:
  sqlalchemy.exc.ProgrammingError:
    column certificates.certificate_number does not exist
```

The public verify endpoint queries a column that does not exist
in the production schema. Students who completed a course cannot
verify their certificate URL — broken since at least the
2026-06-26 review window.

**Fix:**
1. Inspect `apps/api/app/modules/certificates/router.py` to find
   the exact query.
2. `alembic revision --autogenerate -m "add certificates.certificate_number"`
   to create the column.
3. Backfill any historical certificate rows.
4. Return 404 (not 500) for "not found" in the public endpoint.

### Bug 2: `POST /auth/register` returns 500

```
POST /api/v1/auth/register
{
  "email":"smoke-test@demo.kml.kz",
  "first_name":"Smoke",
  "last_name":"Test",
  "password":"smokeTest123!",
  "telegram_id":999999990
}
→ 500 Internal Server Error

Backend traceback:
  AttributeError: 'UserCreate' object has no attribute 'tenant_id'
```

The register endpoint reads `req.tenant_id` (line 183 of
`apps/api/app/modules/auth/router.py`) but `UserCreate` schema
does not declare the field. So the schema accepts the request but
the handler crashes when it tries to access the missing attribute.

**Fix:** Add `tenant_id: UUID | None = None` to `UserCreate` in
`apps/api/app/modules/auth/schemas.py` — and resolve the tenant
from the email domain (the existing logic at line 180 already
tries that). The handler should not require the client to send
`tenant_id`; it should derive it.

### Bug 3: `POST /telegram/webhook` accepts traffic without secret

```
POST /api/v1/telegram/webhook
Content-Type: application/json
{}
→ 200 OK {"ok":true}
```

The webhook should be 404 (or 401) when called without the
configured `TELEGRAM_WEBHOOK_SECRET`. The handler currently
accepts any payload and returns `{"ok": true}`.

**Why this matters:** if the URL is exposed in any logs or
browser history, an attacker can spam the webhook with
malformed payloads. Worse, if the handler routes to
`telegram.py::process_update` even on empty input, the bot
can be made to call `sendMessage` to arbitrary chat_ids using
our bot identity.

**Fix:** Add `if not secrets_match: raise HTTPException(404)`
as the first thing in the handler. Lesson 9 in `docs/LESSONS.md`
already covers the URL-secret pattern.

## AI jobs landscape

8 historical jobs in `/ai/jobs`. Mix of 4 completed and 4 failed.

Failures split into two distinct groups:

### 3a. Older pgvector SQL bug (now fixed)

```
syntax error at or near ":"
[SQL: SELECT text, doc_name, headings,
           1 - (embedding <=> :emb::vector) as distance
      FROM document_embeddings
      WHERE doc_id IN ($1)
      ORDER BY distance
      LIMIT $2]
```

These jobs ran on 2026-06-24 and 2026-06-25, before the
`CAST(:emb AS vector)` fix in `apps/api/app/modules/ai/ingestion.py:303`.
The fix is already in master; no new action needed beyond
instructing Askar that the historical failed jobs are pre-fix
artefacts and can be ignored.

### 3b. Embeddings not written for documents

```
None of the 1 selected document(s) have embeddings.
Re-upload them and try again.
```

This is the **post-fix** error path. The document was uploaded
but `embedding_status` is "success" while the embeddings table
has no rows. Lesson 5b in `docs/LESSONS.md` (PgBouncer
transaction pooling) is the likely cause. To verify:

1. Get the doc_id from the failed job's ingestion log.
2. Open a **fresh** session and `SELECT count(*) FROM document_embeddings WHERE doc_id = ...`.
3. If 0 → re-upload the document after the Round 4-5 fix is deployed.
4. If > 0 → it's the session-pooling visibility issue, fix
   the read path in the same way we did for ingest.

### 3c. Qwen 502/530 (external, out of our control)

```
Server error '530 <none>' for url 'https://qwen.kml.kz/v1/chat/completions'
Server error '502 Bad Gateway' for url 'https://qwen.kml.kz/v1/chat/completions'
```

The DGX hosting Qwen was offline / overloaded. The R5 fix
added DeepSeek as fallback, so retrying should succeed.

## Demo tenant state (interesting because it is real)

- **7 courses** total, mix of `draft` and `published`. Some have
  `review_status=approved` and `published_at=null` (approved but
  not yet published — likely workflow gap).
- **1 position** ("Главный" / "Chief"), 1 employee assigned.
- **1 enrollment** total, 0 completed.
- **2 quizzes** attached to 2 lessons, 0 attempts in history.
- **0 certificates** issued.

This tells us: the demo tenant has the structure for B1c
(position → employee → course) but the actual B1c apply-rules
flow has not been run end-to-end here. We need Askar to do the
UI smoke next.

## What is NOT in this report

- Real UI smoke (login, navigation, sidebar) — needs Askar.
- Cross-tenant isolation tests — should add per ADR-0012.
- `apply-rules` end-to-end via `/admin/staff/import/commit` —
  blocked on real tenant + Excel upload.
- Performance / load testing.
- Real mobile smoke (out of TZ scope for v1.0).

## Recommended next actions

1. **Fix Bug 1** (certificates/verify column missing) — 30 min.
2. **Fix Bug 2** (register UserCreate schema) — 5 min.
3. **Fix Bug 3** (telegram webhook auth) — 5 min.
4. **Re-upload the document that produced the "no embeddings"
   job** and verify a new generation job succeeds end-to-end.
5. **Run a real `/admin/staff/import/commit` smoke** with a
   3-row CSV (Askar does this; agent observes the apply-rules
   task progress and the resulting enrollments).
6. **Add 1 integration test per critical endpoint** (Lesson 5b
   follow-up: pool visibility for `document_embeddings`).
