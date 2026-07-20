"""RLS FORCE row level security + dedicated application role with NOBYPASSRLS.

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-28

Background (see docs/audit-2026-06-28-full.md §3.1):
    0019 added RLS policies (`ENABLE ROW LEVEL SECURITY`) but did NOT call
    `FORCE ROW LEVEL SECURITY`. Per PostgreSQL semantics, the table OWNER
    bypasses RLS by default. Since the application connects as `postgres`
    (Supabase service role) or the table owner, all policies are effectively
    dead code — the app has relied entirely on ORM `tenant_id` filters.

This migration closes that gap by:
    1. Calling `ALTER TABLE ... FORCE ROW LEVEL SECURITY` on every
       tenant-scoped table. FORCE makes RLS apply even to the table owner.
    2. Validating the infrastructure-managed `lms_app` role has
       `NOBYPASSRLS` and granting it the minimum privileges needed to operate.
    3. Documenting the required `DATABASE_URL` swap in the migration
       upgrade/downgrade notes (the URL itself lives in env vars, not
       migration code).

PostgreSQL role creation and attribute changes require cluster-level rights.
Provision `lms_app` before Alembic; the migration fails closed if the role is
missing, is a superuser, or can bypass RLS.

Operational checklist (DO AFTER deploying this migration):
    a) On Supabase: create the `lms_app` role manually (Dashboard →
       Database → Roles → Create role), set a strong password, grant
       `NOBYPASSRLS` and the read/write privileges on the `public` schema
       (or the schema where LMS tables live).
    b) Update `DATABASE_URL` env var on Render to use `lms_app` instead
       of `postgres`. The connection string should look like:
           postgresql://lms_app:<password>@aws-1-eu-central-1.pooler.supabase.com:5432/postgres
    c) Verify with: `SELECT current_user, current_setting('is_superuser');`
       expected: lms_app, off
    d) Smoke test: log in as a tenant user, confirm cross-tenant access
       still returns 404 (RLS should now block at the DB layer even if
       an ORM filter is missing).

Downgrade is intentionally NOT implemented for FORCE — removing it would
re-open the bypass. Operators must manually `ALTER TABLE ... NO FORCE
ROW LEVEL SECURITY` if rollback is absolutely necessary.
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


TENANT_TABLES = [
    "users",
    "courses",
    "modules",
    "lessons",
    "enrollments",
    "progress",
    "documents",
    "document_embeddings",
    "quizzes",
    "quiz_attempts",
    "quiz_assignments",
    "certificates",
    "audit_logs",
    "positions",
    "ai_jobs",
    "tenant_settings",
    "user_roles",
    "user_sessions",
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. FORCE RLS on every tenant table.
    #
    # Without FORCE the table owner bypasses RLS (Postgres default).
    # With FORCE, RLS applies even to the owner — which is exactly what
    # we want, because the application connection role should be the
    # owner (or equivalent) so it can run DDL/DML while still being
    # subject to RLS.
    #
    # ALTER TABLE ... FORCE is idempotent at the SQL level — Postgres
    # accepts it as a no-op if RLS is already forced.
    # ------------------------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # ------------------------------------------------------------------
    # 2. Create the dedicated `lms_app` role with NOBYPASSRLS.
    #
    # In a managed Postgres (Supabase / Render Postgres), the connecting
    # role is usually `postgres` (a superuser) which can never be
    # RLS-bound. The fix is a dedicated application role that:
    #   - is NOT a superuser
    #   - has `NOBYPASSRLS` so FORCE applies to it
    #   - has USAGE on the public schema
    #   - has SELECT/INSERT/UPDATE/DELETE on the tenant tables
    #
    # We create the role + grant minimal privileges here. The password
    # is supplied at deploy time via DATABASE_URL — we do NOT bake
    # credentials into the migration.
    #
    # Note: in Supabase the public schema is owned by `pg_database_owner`
    # and managed via the Dashboard; the GRANT statements below may
    # already be true after the initial schema setup. They are
    # idempotent — re-granting is a no-op.
    # ------------------------------------------------------------------
    op.execute("""
        DO $$
        DECLARE
            app_role RECORD;
        BEGIN
            SELECT rolsuper, rolbypassrls
            INTO app_role
            FROM pg_roles
            WHERE rolname = 'lms_app';

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Required role lms_app is missing; provision it with LOGIN NOSUPERUSER NOBYPASSRLS before running migrations';
            END IF;

            IF app_role.rolsuper OR app_role.rolbypassrls THEN
                RAISE EXCEPTION
                    'Role lms_app must be NOSUPERUSER NOBYPASSRLS before running migrations';
            END IF;
        END
        $$;
    """)

    op.execute("GRANT USAGE ON SCHEMA public TO lms_app")

    # Grant table-level privileges. Idempotent.
    for table in TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")

    # Sequences (for SERIAL/IDENTITY columns). Most UUID PKs don't need
    # these, but `user_invitations` and a few other tables use sequences.
    op.execute("""
        DO $$
        DECLARE
            seq_record RECORD;
        BEGIN
            FOR seq_record IN
                SELECT sequence_name FROM information_schema.sequences
                WHERE sequence_schema = 'public'
            LOOP
                EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I TO lms_app', seq_record.sequence_name);
            END LOOP;
        END
        $$;
    """)


def downgrade() -> None:
    # NOTE: downgrading this migration re-opens the RLS bypass hole.
    # We intentionally do NOT auto-downgrade FORCE — operators must
    # make that call manually after audit.
    #
    # What downgrade DOES undo:
    #   - the lms_app role grants (so it can be dropped cleanly)
    #   - the lms_app role itself
    # What downgrade DOES NOT undo:
    #   - the FORCE flag on tables

    # Revoke privileges first.
    for table in TENANT_TABLES:
        op.execute(f"REVOKE ALL PRIVILEGES ON {table} FROM lms_app")

    op.execute("REVOKE USAGE ON SCHEMA public FROM lms_app")

    # The cluster role itself is infrastructure-owned and is intentionally
    # not dropped by an application schema downgrade.
    # We do NOT undo FORCE — see note above.
