"""Bind public lead inserts to an explicit transaction-local RLS context.

Revision ID: 0090
Revises: 0089
Create Date: 2026-08-07
"""

from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_leads_public_insert ON tenant_leads")
    op.execute(
        """
        CREATE POLICY tenant_leads_public_insert ON tenant_leads
        FOR INSERT
        TO PUBLIC
        WITH CHECK (
            tenant_id IS NULL
            AND source = 'landing_form'
            AND current_setting('app.public_lead_insert', true) = 'true'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_leads_public_insert ON tenant_leads")
    op.execute(
        """
        CREATE POLICY tenant_leads_public_insert ON tenant_leads
        FOR INSERT
        TO lms_app
        WITH CHECK (tenant_id IS NULL AND source = 'landing_form')
        """
    )
