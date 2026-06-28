# ADR-0004: Force RLS and dedicated application role

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context:** audit-2026-06-28-full.md §3.1 (Critical), §3.3, §3.5

## Context and problem

Migration 0019 added Row-Level Security policies to every tenant-scoped
table (`ENABLE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)`).
However, the migration did **not** call `FORCE ROW LEVEL SECURITY`.

Per PostgreSQL semantics, the table OWNER bypasses RLS by default.
Since the application connects to the production database as `postgres`
(Supabase `service_role` style), all policies are effectively dead
code. The application has been relying entirely on ORM-level
`tenant_id` filters — any missing filter is a cross-tenant leak.

`docs/audit-2026-06-28-full.md §3.1` flagged this as a Critical issue.

## Decision

We introduce defense-in-depth at the database layer:

1. **Migration 0033** runs `ALTER TABLE <tenant_table> FORCE ROW LEVEL SECURITY`
   on every tenant-scoped table. With FORCE, RLS applies even to the
   table owner, so policies cannot be silently bypassed by changing
   the connecting role.

2. **A dedicated `lms_app` PostgreSQL role** is created in the same
   migration with:
   - `NOBYPASSRLS` (so FORCE applies to it)
   - `NOLOGIN` (no direct interactive login)
   - minimal `SELECT/INSERT/UPDATE/DELETE` on tenant tables
   - `USAGE` on the `public` schema
   - `USAGE, SELECT` on sequences (for SERIAL/IDENTITY PKs)

3. **`DATABASE_URL` env var must point at `lms_app`**, not at
   `postgres`. The `lms_dev_password_2026` / Supabase-managed
   `postgres.<ref>` style URLs from .env files must be replaced.

## Operational rollout

The migration itself is one-shot, but the URL swap is a coordinated
production change with two possible rollback paths. Runbook:

### Pre-deploy

1. On Supabase Dashboard → Database → Roles → **Create role**:
   - Name: `lms_app`
   - Password: 32+ random chars (store in password manager)
   - Privileges: leave at default (none)
2. Note the new connection string:
   `postgresql://lms_app:<password>@aws-1-eu-central-1.pooler.supabase.com:5432/postgres`

### Deploy

1. Merge migration 0033 to main.
2. Wait for Render auto-deploy (migration runs in `alembic upgrade head`
   inside `app/main.py` startup hook).
3. Verify FORCE applied:
   ```sql
   SELECT relname, relrowsecurity, relforcerowsecurity
   FROM pg_class
   WHERE relname IN ('users','courses','documents',...)
   ORDER BY relname;
   -- Expect relforcerowsecurity = t for every row
   ```
4. Verify `lms_app` role exists with NOBYPASSRLS:
   ```sql
   SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'lms_app';
   -- Expect rolsuper=f, rolbypassrls=f
   ```

### Cutover (the dangerous step)

5. Update `DATABASE_URL` env var on Render to use `lms_app` connection
   string (not `postgres`). Trigger a manual redeploy.
6. **Watch logs carefully** for ~30 minutes. The first RLS violation
   surfaces as `new row violates row-level security policy` on INSERT,
   or empty result sets on SELECT.
7. Smoke test:
   - Log in as tenant A user → verify can see own data
   - Attempt cross-tenant URL → expect 404 from the API
   - Try directly in psql as `lms_app`:
     ```sql
     SET app.tenant_id = '<tenant_A_uuid>';
     SELECT count(*) FROM courses; -- should equal tenant_A's count
     SET app.tenant_id = '<tenant_B_uuid>';
     SELECT count(*) FROM courses; -- should equal tenant_B's count, NOT the sum
     ```

### Rollback

If RLS breaks a critical flow in production, fastest recovery is
restoring the previous `DATABASE_URL` (pointing at `postgres`) via
Render env override + redeploy. The `lms_app` role can stay; it just
won't be used. Migration 0033's `downgrade()` will NOT remove the
FORCE flag (deliberately — re-opening the bypass should require an
explicit, audited decision).

## Consequences

### Positive

- A single missing ORM `tenant_id` filter no longer leaks data across
  tenants. RLS blocks at the database layer.
- The `lms_app` role cannot escalate to `postgres` (no superuser).
- Audit evidence is now at the DB layer, not just in application logs.

### Negative / costs

- Migration 0033 is one-way in practice. Rolling back FORCE requires a
  manual `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY` per table.
- The `lms_app` role adds a new secret to manage (its password).
- Every connection through `lms_app` is subject to `set_current_tenant()`
  in app code. If a code path forgets to call it, the query returns
  zero rows (because `current_setting('app.tenant_id', true)` is empty
  and `''::uuid` doesn't match any tenant_id). This is a **safer**
  failure mode than the current bypass — but it can confuse developers
  who expect unfiltered data. New starters should read
  `app/core/auth.py::get_current_user` to see how the tenant context
  is set per-request.

## Verification

After cutover, this query (run as `lms_app` without setting tenant
context) MUST return zero rows from any tenant table — proving the
RLS defense is active:

```sql
SELECT count(*) FROM courses;      -- expect 0
SELECT count(*) FROM users;        -- expect 0
SELECT count(*) FROM documents;    -- expect 0
```

If any returns non-zero, FORCE is not active for that table or the
connecting role is bypassing RLS — investigate immediately.

## Cross-references

- Migration: `apps/api/alembic/versions/0033_force_rls_and_lms_app_role.py`
- Audit: `docs/audit-2026-06-28-full.md` §3.1, §3.3, §3.5
- AGENTS.md: §Multi-tenancy, §Security checklist
- Related: ADR-0003 (multi-tenant architecture)