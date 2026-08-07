"""Add a bounded RLS-safe function for public lead capture.

Revision ID: 0091
Revises: 0090
Create Date: 2026-08-07
"""

from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


FUNCTION_SIGNATURE = "insert_public_tenant_lead(text, text, text, text, text, text, text, text)"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION insert_public_tenant_lead(
            p_company_name text,
            p_contact_name text,
            p_email text,
            p_phone text,
            p_employee_count_range text,
            p_preferred_language text,
            p_intent text,
            p_message text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            created_id uuid;
        BEGIN
            PERFORM set_config('app.public_lead_insert', 'true', true);

            INSERT INTO tenant_leads (
                id,
                tenant_id,
                company_name,
                contact_name,
                email,
                phone,
                employee_count_range,
                preferred_language,
                intent,
                status,
                source,
                message
            )
            VALUES (
                gen_random_uuid(),
                NULL,
                p_company_name,
                p_contact_name,
                p_email,
                p_phone,
                p_employee_count_range,
                p_preferred_language,
                p_intent,
                'lead_submitted',
                'landing_form',
                p_message
            )
            RETURNING id INTO created_id;

            RETURN created_id;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} TO lms_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}")
