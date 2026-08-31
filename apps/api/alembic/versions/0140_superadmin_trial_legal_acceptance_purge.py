"""Allow exact-tenant superadmin deletion of registration legal acceptance.

Revision ID: 0140
Revises: 0139
Create Date: 2026-08-31
"""

from alembic import op

revision = "0140"
down_revision = "0139"
branch_labels = None
depends_on = None

POLICY_NAME = "registration_legal_acceptances_superadmin_delete"


def upgrade() -> None:
    op.execute("GRANT DELETE ON registration_legal_acceptances TO lms_app")
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME}
        ON registration_legal_acceptances
        FOR DELETE TO lms_app
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND COALESCE(current_setting('app.is_superadmin', true), '') = 'true'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON registration_legal_acceptances"
    )
    op.execute("REVOKE DELETE ON registration_legal_acceptances FROM lms_app")
