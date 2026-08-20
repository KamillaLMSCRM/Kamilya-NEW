"""Promote saved mappings to versioned tenant workbook profiles.

Revision ID: 0115
Revises: 0114
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_import_mappings", sa.Column("workbook_signature", sa.Text(), nullable=True))
    op.add_column(
        "staff_import_mappings",
        sa.Column(
            "profile_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "staff_import_mappings",
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="adaptive-v1"),
    )
    op.add_column("staff_import_mappings", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "staff_import_mappings",
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_staff_import_mappings_approved_by_users",
        "staff_import_mappings",
        "users",
        ["approved_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_staff_import_mappings_signature",
        "staff_import_mappings",
        "workbook_signature IS NULL OR workbook_signature ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_staff_import_mappings_profile_object",
        "staff_import_mappings",
        "jsonb_typeof(profile_json) = 'object'",
    )
    op.create_check_constraint(
        "ck_staff_import_mappings_profile_approval",
        "staff_import_mappings",
        "(workbook_signature IS NULL AND approved_at IS NULL AND approved_by IS NULL) "
        "OR (workbook_signature IS NOT NULL AND approved_at IS NOT NULL AND approved_by IS NOT NULL)",
    )
    op.create_index(
        "uq_staff_import_mappings_tenant_signature",
        "staff_import_mappings",
        ["tenant_id", "workbook_signature"],
        unique=True,
        postgresql_where=sa.text("workbook_signature IS NOT NULL"),
    )
    op.execute(
        r"""
        CREATE FUNCTION validate_staff_import_mapping_profile_approval()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE approver_tenant uuid;
        BEGIN
          IF NEW.workbook_signature IS NOT NULL THEN
            SELECT tenant_id INTO approver_tenant FROM users WHERE id = NEW.approved_by;
            IF approver_tenant IS NULL OR approver_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION 'staff import mapping approver tenant mismatch'
                USING ERRCODE='foreign_key_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_staff_import_mapping_profile_approval
        BEFORE INSERT OR UPDATE ON staff_import_mappings
        FOR EACH ROW EXECUTE FUNCTION validate_staff_import_mapping_profile_approval()
        """
    )


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (
          SELECT 1 FROM staff_import_mappings
          WHERE workbook_signature IS NOT NULL OR profile_json <> '{}'::jsonb
        ) THEN
          RAISE EXCEPTION '0115 downgrade refused: approved workbook mapping profiles exist';
        END IF;
        END $$"""
    )
    op.execute("DROP FUNCTION IF EXISTS validate_staff_import_mapping_profile_approval() CASCADE")
    op.drop_index("uq_staff_import_mappings_tenant_signature", table_name="staff_import_mappings")
    op.drop_constraint("ck_staff_import_mappings_profile_approval", "staff_import_mappings")
    op.drop_constraint("ck_staff_import_mappings_profile_object", "staff_import_mappings")
    op.drop_constraint("ck_staff_import_mappings_signature", "staff_import_mappings")
    op.drop_constraint(
        "fk_staff_import_mappings_approved_by_users",
        "staff_import_mappings",
        type_="foreignkey",
    )
    op.drop_column("staff_import_mappings", "approved_at")
    op.drop_column("staff_import_mappings", "approved_by")
    op.drop_column("staff_import_mappings", "schema_version")
    op.drop_column("staff_import_mappings", "profile_json")
    op.drop_column("staff_import_mappings", "workbook_signature")
