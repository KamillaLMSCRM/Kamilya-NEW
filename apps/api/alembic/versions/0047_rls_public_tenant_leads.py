"""Allow public landing lead capture under RLS.

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-02
"""

from alembic import op


revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS tenant_leads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE IF EXISTS tenant_leads FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_leads TO lms_app")

    op.execute("DROP POLICY IF EXISTS tenant_leads_tenant_isolation ON tenant_leads")
    op.execute(
        """
        CREATE POLICY tenant_leads_tenant_isolation ON tenant_leads
        FOR ALL
        TO lms_app
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    op.execute("DROP POLICY IF EXISTS tenant_leads_public_insert ON tenant_leads")
    op.execute(
        """
        CREATE POLICY tenant_leads_public_insert ON tenant_leads
        FOR INSERT
        TO lms_app
        WITH CHECK (tenant_id IS NULL AND source = 'landing_form')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_leads_public_insert ON tenant_leads")
    op.execute("DROP POLICY IF EXISTS tenant_leads_tenant_isolation ON tenant_leads")
