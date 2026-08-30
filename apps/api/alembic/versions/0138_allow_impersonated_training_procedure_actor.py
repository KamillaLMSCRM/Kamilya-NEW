"""Allow an audited platform impersonation to omit tenant procedure authors.

Revision ID: 0138
Revises: 0137
Create Date: 2026-08-30

Ordinary tenant mutations retain strict same-tenant author validation. A
platform superadmin is never rewritten as a tenant user: the nullable author
is paired with the existing tenant audit event carrying the real operator.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0138"
down_revision = "0137"
branch_labels = None
depends_on = None


STRICT_OWNERSHIP_FUNCTION = """
CREATE OR REPLACE FUNCTION validate_training_procedure_ownership()
RETURNS trigger AS $$
DECLARE creator_tenant uuid;
DECLARE updater_tenant uuid;
BEGIN
    SELECT tenant_id INTO creator_tenant FROM users WHERE id = NEW.created_by_user_id;
    SELECT tenant_id INTO updater_tenant FROM users WHERE id = NEW.updated_by_user_id;
    IF creator_tenant IS NULL OR creator_tenant <> NEW.tenant_id
       OR updater_tenant IS NULL OR updater_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION 'Training procedure actors must belong to the same tenant'
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.alter_column("training_procedures", "created_by_user_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("training_procedures", "updated_by_user_id", existing_type=sa.UUID(), nullable=True)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_training_procedure_ownership()
        RETURNS trigger AS $$
        DECLARE creator_tenant uuid;
        DECLARE updater_tenant uuid;
        BEGIN
            IF NEW.created_by_user_id IS NOT NULL THEN
                SELECT tenant_id INTO creator_tenant FROM users WHERE id = NEW.created_by_user_id;
                IF creator_tenant IS NULL OR creator_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Training procedure creator must belong to the same tenant'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            IF NEW.updated_by_user_id IS NOT NULL THEN
                SELECT tenant_id INTO updater_tenant FROM users WHERE id = NEW.updated_by_user_id;
                IF updater_tenant IS NULL OR updater_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Training procedure updater must belong to the same tenant'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM training_procedures
                WHERE created_by_user_id IS NULL OR updated_by_user_id IS NULL
            ) THEN
                RAISE EXCEPTION 'Cannot restore strict training procedure authors while audited impersonation rows exist';
            END IF;
        END $$;
        """
    )
    op.execute(STRICT_OWNERSHIP_FUNCTION)
    op.alter_column("training_procedures", "updated_by_user_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("training_procedures", "created_by_user_id", existing_type=sa.UUID(), nullable=False)
