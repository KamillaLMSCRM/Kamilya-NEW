"""Restore public kiosk lookup under forced tenant RLS.

Revision ID: 0119
Revises: 0118
"""

from alembic import op

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The kiosk URL token is itself the public credential.  Before a request
    # knows the tenant UUID, expose exactly the one kiosk row whose 144-bit
    # random token matches the transaction-local context.  The ordinary
    # tenant_isolation policy continues to protect every tenant-authenticated
    # operation and all other rows.
    op.execute("DROP POLICY IF EXISTS kiosk_links_public_token_lookup ON kiosk_links")
    op.execute(
        """
        CREATE POLICY kiosk_links_public_token_lookup ON kiosk_links
        FOR SELECT TO lms_app
        USING (
            token = NULLIF(current_setting('app.kiosk_token', true), '')
        )
        """
    )

    # This older SECURITY DEFINER function was created after kiosk_links had
    # FORCE RLS.  Its owner therefore remained subject to RLS and it returned
    # NULL for every valid token.  The application now uses the scoped policy
    # above, so remove the misleading bypass-shaped API entirely.
    op.execute("DROP FUNCTION IF EXISTS lookup_kiosk_tenant_by_token(text)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kiosk_links_public_token_lookup ON kiosk_links")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION lookup_kiosk_tenant_by_token(kiosk_token text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT tenant_id
              FROM kiosk_links
             WHERE token = kiosk_token
             LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lookup_kiosk_tenant_by_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_kiosk_tenant_by_token(text) TO lms_app")
