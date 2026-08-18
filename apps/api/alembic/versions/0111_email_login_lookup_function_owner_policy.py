"""Allow the bounded email-login lookup through FORCE RLS.

Revision ID: 0111
Revises: 0110
Create Date: 2026-08-18

The managed-provider baseline owned ``lookup_login_user_by_email`` with a role
that bypassed row-level security.  A fresh least-privilege cluster owns the
SECURITY DEFINER function with the migration role instead.  With FORCE RLS on
``users`` the function then returns no row, so the intentionally-neutral
request-code endpoint reports success without creating or sending an OTP.

The new policy is granted only to the resolved function owner.  The runtime
application role receives only EXECUTE on the bounded function, not direct
table visibility.  No role is granted a row-security bypass.
"""

from alembic import op

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None


_FUNCTION_SQL = """
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
    WHERE lower(btrim(u.email)) = lower(btrim(login_email))
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
$$
"""


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_auth_email_lookup_function_owner ON users")
    op.execute(
        """
        DO $$
        DECLARE
            function_owner name;
        BEGIN
            SELECT owner_role.rolname
              INTO function_owner
              FROM pg_proc AS function
              JOIN pg_roles AS owner_role ON owner_role.oid = function.proowner
             WHERE function.oid =
                'lookup_login_user_by_email(text)'::regprocedure;

            IF function_owner IS NULL THEN
                RAISE EXCEPTION
                    'lookup_login_user_by_email owner could not be resolved';
            END IF;
            IF function_owner = 'lms_app' THEN
                RAISE EXCEPTION
                    'bounded SECURITY DEFINER functions must not be owned by lms_app';
            END IF;

            EXECUTE format(
                'CREATE POLICY users_auth_email_lookup_function_owner ON users '
                'FOR SELECT TO %I USING (true)',
                function_owner
            );
        END
        $$;
        """
    )
    op.execute(_FUNCTION_SQL)
    op.execute("REVOKE ALL ON FUNCTION lookup_login_user_by_email(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_login_user_by_email(text) TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_auth_email_lookup_function_owner ON users")
    op.execute("REVOKE ALL ON FUNCTION lookup_login_user_by_email(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_login_user_by_email(text) TO lms_app")
