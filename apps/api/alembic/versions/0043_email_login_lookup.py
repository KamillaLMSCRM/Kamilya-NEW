"""Add safe email login lookup for RLS runtime role.

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-01
"""

from alembic import op


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION lookup_login_user_by_email(login_email text)
        RETURNS TABLE (
            user_id uuid,
            tenant_id uuid,
            role text,
            is_active boolean
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT u.id, u.tenant_id, u.role, u.is_active
            FROM users u
            WHERE lower(u.email) = lower(login_email)
            ORDER BY u.created_at ASC
            LIMIT 1
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lookup_login_user_by_email(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_login_user_by_email(text) TO lms_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS lookup_login_user_by_email(text)")
