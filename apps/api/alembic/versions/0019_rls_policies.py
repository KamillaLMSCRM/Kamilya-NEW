"""RLS policies + set_current_tenant function

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "users", "courses", "modules", "lessons",
    "enrollments", "progress", "documents", "document_embeddings",
    "quizzes", "quiz_attempts", "quiz_assignments",
    "certificates", "audit_logs", "positions",
    "ai_jobs", "tenant_settings", "user_roles", "user_sessions",
]


def upgrade() -> None:
    # Create set_current_tenant function
    op.execute("""
        CREATE OR REPLACE FUNCTION set_current_tenant(tenant_uuid UUID)
        RETURNS void AS $$
        BEGIN
            PERFORM set_config('app.tenant_id', tenant_uuid::text, true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create reset_tenant function
    op.execute("""
        CREATE OR REPLACE FUNCTION reset_tenant()
        RETURNS void AS $$
        BEGIN
            PERFORM set_config('app.tenant_id', '', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Enable RLS + create policies on all tenant tables
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS set_current_tenant(UUID)")
    op.execute("DROP FUNCTION IF EXISTS reset_tenant()")
