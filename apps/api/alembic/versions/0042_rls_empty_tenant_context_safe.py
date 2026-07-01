"""Make tenant RLS policies safe when app.tenant_id is empty.

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-01
"""

from alembic import op


revision = "0042"
down_revision = "0041"
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
    "user_invitations",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reset_tenant()
        RETURNS void AS $$
        BEGIN
            PERFORM set_config('app.tenant_id', '', true);
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )
