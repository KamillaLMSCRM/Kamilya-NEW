"""Persist refresh-token allowlist sessions, including platform operators.

Revision ID: 0093
Revises: 0092
"""

from alembic import op


revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_sessions ALTER COLUMN tenant_id DROP NOT NULL")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_sessions")
    op.execute("""
        CREATE POLICY tenant_isolation ON user_sessions
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            OR (tenant_id IS NULL AND current_setting('app.is_superadmin', true) = 'true')
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            OR (tenant_id IS NULL AND current_setting('app.is_superadmin', true) = 'true')
        )
    """)
    op.execute("ALTER TABLE user_sessions FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DELETE FROM user_sessions WHERE tenant_id IS NULL")
    op.execute("ALTER TABLE user_sessions ALTER COLUMN tenant_id SET NOT NULL")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_sessions")
    op.execute("""
        CREATE POLICY tenant_isolation ON user_sessions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
