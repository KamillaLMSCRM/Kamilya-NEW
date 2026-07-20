"""Allow validated superadmin sessions through RLS.

Revision ID: 0045
Revises: 0044
Create Date: 2026-07-01
"""

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


SUPERADMIN_TABLES = (
    "audit_logs",
    "courses",
    "documents",
    "enrollments",
    "tenant_leads",
    "tenant_usage",
    "tenants",
    "users",
)


def upgrade() -> None:
    for table in SUPERADMIN_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_superadmin_session ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_superadmin_session ON {table}
            FOR ALL
            TO lms_app
            USING (current_setting('app.is_superadmin', true) = 'true')
            WITH CHECK (current_setting('app.is_superadmin', true) = 'true')
            """
        )


def downgrade() -> None:
    for table in SUPERADMIN_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_superadmin_session ON {table}")
