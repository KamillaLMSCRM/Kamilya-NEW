"""Prefer tenant admin accounts for email OTP login.

Revision ID: 0048
Revises: 0047
Create Date: 2026-07-03
"""

from alembic import op


revision = "0048"
down_revision = "0047"
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
            SELECT
                u.id,
                u.tenant_id,
                COALESCE(ur.role, u.role) AS role,
                u.is_active
            FROM users u
            LEFT JOIN LATERAL (
                SELECT role
                FROM user_roles
                WHERE user_id = u.id AND tenant_id = u.tenant_id
                ORDER BY CASE role
                    WHEN 'superadmin' THEN 1
                    WHEN 'admin' THEN 2
                    WHEN 'org_admin' THEN 3
                    WHEN 'methodologist' THEN 4
                    WHEN 'teacher' THEN 5
                    WHEN 'student' THEN 6
                    ELSE 7
                END
                LIMIT 1
            ) ur ON true
            WHERE lower(u.email) = lower(login_email)
            ORDER BY
                CASE COALESCE(ur.role, u.role)
                    WHEN 'superadmin' THEN 1
                    WHEN 'admin' THEN 2
                    WHEN 'org_admin' THEN 3
                    WHEN 'methodologist' THEN 4
                    WHEN 'teacher' THEN 5
                    WHEN 'student' THEN 6
                    ELSE 7
                END,
                u.created_at DESC
            LIMIT 1
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lookup_login_user_by_email(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_login_user_by_email(text) TO lms_app")


def downgrade() -> None:
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
