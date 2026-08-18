"""Allow bounded CRM outbox functions through FORCE RLS.

Revision ID: 0110
Revises: 0109
Create Date: 2026-08-17

Managed clusters historically created the 0094 SECURITY DEFINER functions
under a role that bypassed RLS. A least-privilege fresh cluster owns them with
the migration role instead. FORCE RLS then hides tenant_leads and
crm_lead_outbox from the function owner, even though the lms_app caller has the
correct tenant context.

These policies apply only to the actual function owner. They do not grant the
application role direct outbox access and do not give any role BYPASSRLS.
"""

from alembic import op

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
                'crm_enqueue_tenant_lead_outbox(uuid,uuid,jsonb)'::regprocedure;

            IF function_owner IS NULL THEN
                RAISE EXCEPTION
                    'crm_enqueue_tenant_lead_outbox owner could not be resolved';
            END IF;
            IF function_owner = 'lms_app' THEN
                RAISE EXCEPTION
                    'bounded SECURITY DEFINER functions must not be owned by lms_app';
            END IF;

            EXECUTE format(
                'CREATE POLICY tenant_leads_function_owner ON tenant_leads '
                'FOR ALL TO %I '
                'USING ('
                'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid '
                'OR current_setting(''app.public_lead_insert'', true) = ''true'' '
                'OR current_setting(''app.is_superadmin'', true) = ''true'') '
                'WITH CHECK ('
                'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid '
                'OR current_setting(''app.public_lead_insert'', true) = ''true'' '
                'OR current_setting(''app.is_superadmin'', true) = ''true'')',
                function_owner
            );
            EXECUTE format(
                'CREATE POLICY crm_lead_outbox_function_owner ON crm_lead_outbox '
                'FOR ALL TO %I USING (true) WITH CHECK (true)',
                function_owner
            );
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS crm_lead_outbox_function_owner ON crm_lead_outbox")
    op.execute("DROP POLICY IF EXISTS tenant_leads_function_owner ON tenant_leads")
