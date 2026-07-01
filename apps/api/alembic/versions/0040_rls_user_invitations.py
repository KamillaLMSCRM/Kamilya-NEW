"""Enable and force RLS for user invitations.

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-01

`user_invitations` is tenant-scoped and stores invite tokens/audit fields.
It was missed in 0039, so this small follow-up applies the same tenant
isolation policy.
"""

from alembic import op


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS user_invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE IF EXISTS user_invitations FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_invitations")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON user_invitations
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_invitations TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_invitations")
