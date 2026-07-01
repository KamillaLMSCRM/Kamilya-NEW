"""Allow runtime role to read platform superadmin login row.

Revision ID: 0044
Revises: 0043
Create Date: 2026-07-01
"""

from alembic import op


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS users_platform_superadmin_login ON users;
        CREATE POLICY users_platform_superadmin_login ON users
        FOR SELECT
        TO lms_app
        USING (tenant_id IS NULL AND role = 'superadmin');
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_platform_superadmin_login ON users")
