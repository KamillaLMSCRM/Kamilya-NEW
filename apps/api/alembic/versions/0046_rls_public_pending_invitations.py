"""Allow public pending invitation token lookup.

Revision ID: 0046
Revises: 0045
Create Date: 2026-07-01

The accept-invite flow starts without a JWT, so there is no tenant context yet.
The API must first resolve a pending invitation token, then it can set
app.tenant_id from that row and continue under the normal tenant RLS policy.
"""

from alembic import op


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_invitations_public_pending_lookup ON user_invitations")
    op.execute(
        """
        CREATE POLICY user_invitations_public_pending_lookup ON user_invitations
        FOR SELECT
        USING (status = 'pending')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_invitations_public_pending_lookup ON user_invitations")
