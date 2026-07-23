"""Add token-scoped tenant lookup for public kiosk access.

Revision ID: 0070
Revises: 0069
"""

from alembic import op


revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION lookup_kiosk_tenant_by_token(text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION lookup_kiosk_tenant_by_token(text) TO lms_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS lookup_kiosk_tenant_by_token(text)")
