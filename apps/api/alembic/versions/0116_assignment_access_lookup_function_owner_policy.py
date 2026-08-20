"""Allow the bounded assignment-token lookup through FORCE RLS.

Revision ID: 0116
Revises: 0115
Create Date: 2026-08-20

The public PIN exchange first resolves a tenant through the SECURITY DEFINER
``lookup_assignment_access_tenant_by_token`` function.  On a least-privilege
PostgreSQL cluster the function owner is still subject to FORCE RLS on
``assignment_access_credentials``.  Without a policy for that exact owner the
bounded lookup sees no active credential and every valid link returns 404.

This migration grants only SELECT visibility to the resolved function owner.
The runtime role retains EXECUTE on the bounded lookup and receives no direct
cross-tenant table visibility or row-security exemption.
"""

from alembic import op

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS assignment_access_lookup_function_owner "
        "ON assignment_access_credentials"
    )
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
                'lookup_assignment_access_tenant_by_token(text)'::regprocedure;

            IF function_owner IS NULL THEN
                RAISE EXCEPTION
                    'lookup_assignment_access_tenant_by_token owner could not be resolved';
            END IF;
            IF function_owner = 'lms_app' THEN
                RAISE EXCEPTION
                    'bounded SECURITY DEFINER functions must not be owned by lms_app';
            END IF;

            EXECUTE format(
                'CREATE POLICY assignment_access_lookup_function_owner '
                'ON assignment_access_credentials FOR SELECT TO %I USING (true)',
                function_owner
            );
        END
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "lookup_assignment_access_tenant_by_token(text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "lookup_assignment_access_tenant_by_token(text) TO lms_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS assignment_access_lookup_function_owner "
        "ON assignment_access_credentials"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "lookup_assignment_access_tenant_by_token(text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "lookup_assignment_access_tenant_by_token(text) TO lms_app"
    )
