"""Enable and force RLS for tenant tables added after migration 0019.

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-01

Migration 0019 enabled tenant RLS for the original LMS tables. Later
features added departments, assignment rules, kiosk links, position JD/quiz
tables, tenant integrations, and LLM usage tables, but did not consistently
add RLS policies. This migration closes that gap and re-applies FORCE RLS to
all tenant-scoped tables.

`provider_keys` is intentionally excluded: tenant_id NULL means a global
platform provider key in v1, so a simple tenant_id policy would hide global
keys from the platform/provider-key service.
"""

from alembic import op


revision = "0039"
down_revision = "0038"
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
    "departments",
    "department_courses",
    "position_courses",
    "kiosk_links",
    "position_jd_versions",
    "position_quizzes",
    "tenant_integrations",
    "tenant_integrations_audit",
    "tenant_llm_usage",
]


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE IF EXISTS {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")


def downgrade() -> None:
    # Keep FORCE RLS in place on downgrade; removing it re-opens the RLS bypass.
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
