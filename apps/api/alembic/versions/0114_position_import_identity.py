"""Add stable import identity metadata to positions.

Revision ID: 0114
Revises: 0113
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0114"
down_revision = "0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("normalized_name", sa.Text(), nullable=True, server_default=""))
    op.add_column("positions", sa.Column("external_key", sa.Text(), nullable=True))
    op.add_column(
        "positions",
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("positions", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute(
        "UPDATE positions SET normalized_name = lower(regexp_replace(btrim(name), '\\s+', ' ', 'g'))"
    )
    op.alter_column("positions", "normalized_name", nullable=False)
    op.create_check_constraint(
        "ck_positions_normalized_name",
        "positions",
        "length(btrim(normalized_name)) > 0",
    )
    op.create_check_constraint(
        "ck_positions_source_metadata_object",
        "positions",
        "jsonb_typeof(source_metadata) = 'object'",
    )
    op.create_index(
        "uq_positions_tenant_external_key",
        "positions",
        ["tenant_id", "external_key"],
        unique=True,
        postgresql_where=sa.text("external_key IS NOT NULL"),
    )
    op.create_index(
        "ix_positions_tenant_department_normalized",
        "positions",
        ["tenant_id", "department_id", "normalized_name"],
    )
    op.execute(
        r"""
        CREATE FUNCTION validate_position_import_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE department_tenant uuid;
        BEGIN
          NEW.name := btrim(NEW.name);
          NEW.normalized_name := lower(regexp_replace(btrim(NEW.name), '\s+', ' ', 'g'));
          NEW.external_key := NULLIF(btrim(NEW.external_key), '');
          IF NEW.department_id IS NOT NULL THEN
            SELECT tenant_id INTO department_tenant FROM departments WHERE id = NEW.department_id;
            IF department_tenant IS NULL OR department_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION 'position organization unit tenant mismatch'
                USING ERRCODE='foreign_key_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_position_import_identity
        BEFORE INSERT OR UPDATE ON positions
        FOR EACH ROW EXECUTE FUNCTION validate_position_import_identity()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM positions WHERE external_key IS NOT NULL LIMIT 1) THEN
            RAISE EXCEPTION '0114 downgrade refused: position import identities exist';
          END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_validate_position_import_identity ON positions")
    op.execute("DROP FUNCTION IF EXISTS validate_position_import_identity()")
    op.drop_index("ix_positions_tenant_department_normalized", table_name="positions")
    op.drop_index("uq_positions_tenant_external_key", table_name="positions")
    op.drop_constraint("ck_positions_source_metadata_object", "positions")
    op.drop_constraint("ck_positions_normalized_name", "positions")
    op.drop_column("positions", "is_active")
    op.drop_column("positions", "source_metadata")
    op.drop_column("positions", "external_key")
    op.drop_column("positions", "normalized_name")
