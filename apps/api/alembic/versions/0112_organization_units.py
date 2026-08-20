"""Expand departments into typed organization units without reclassifying tenants.

Revision ID: 0112
Revises: 0111
Create Date: 2026-08-18

The existing ``departments`` table and all row IDs remain in place. Existing
root rows are deliberately marked as compatibility rows: their real meaning
must be confirmed in a tenant-specific import session, not guessed globally.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column("unit_type", sa.Text(), nullable=True, server_default="department"),
    )
    op.add_column(
        "departments",
        sa.Column("normalized_name", sa.Text(), nullable=True, server_default=""),
    )
    op.add_column(
        "departments",
        sa.Column("external_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "departments",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "departments",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "departments",
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'{"origin":"legacy_adapter"}\'::jsonb'),
        ),
    )
    op.add_column(
        "departments",
        sa.Column("legacy_root", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Production owns this table with the non-BYPASSRLS migration role while
    # the legacy table already has FORCE RLS. Without temporarily restoring
    # normal owner semantics, the backfill UPDATE sees zero rows and the
    # following CHECK validation fails against untouched physical rows.
    # Alembic runs the revision transactionally, so any later failure restores
    # FORCE RLS together with the rest of the revision.
    op.execute("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY")

    # Preserve every existing ID and meaning. Classification as a branch is a
    # tenant-specific approval decision, so all historical roots stay marked
    # as compatibility departments at this point.
    op.execute(
        r"""
        UPDATE departments
           SET unit_type = 'department',
               normalized_name = lower(
                   regexp_replace(btrim(name), '\s+', ' ', 'g')
               ),
               legacy_root = (parent_id IS NULL),
               source_metadata = jsonb_build_object(
                   'origin', 'legacy_migration',
                   'migration', '0112'
               )
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM departments
             WHERE normalized_name IS NULL OR normalized_name = ''
          ) THEN
            RAISE EXCEPTION
              '0112 organization-unit backfill produced an empty normalized name';
          END IF;
        END $$
        """
    )

    op.alter_column("departments", "unit_type", nullable=False)
    op.alter_column("departments", "normalized_name", nullable=False)

    op.create_check_constraint(
        "ck_departments_unit_type",
        "departments",
        "unit_type IN ('branch', 'department')",
    )
    op.create_check_constraint(
        "ck_departments_branch_root",
        "departments",
        "unit_type <> 'branch' OR parent_id IS NULL",
    )
    op.create_check_constraint(
        "ck_departments_department_parent",
        "departments",
        "unit_type <> 'department' OR parent_id IS NOT NULL OR legacy_root",
    )
    op.create_check_constraint(
        "ck_departments_archive_state",
        "departments",
        "(is_active AND archived_at IS NULL) OR " "(NOT is_active AND archived_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_departments_normalized_name",
        "departments",
        "length(btrim(normalized_name)) > 0",
    )
    op.create_check_constraint(
        "ck_departments_source_metadata_object",
        "departments",
        "jsonb_typeof(source_metadata) = 'object'",
    )

    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1
              FROM departments
             WHERE parent_id IS NULL AND is_active
             GROUP BY tenant_id, unit_type, normalized_name
            HAVING count(*) > 1
          ) OR EXISTS (
            SELECT 1
              FROM departments
             WHERE parent_id IS NOT NULL AND is_active
             GROUP BY tenant_id, parent_id, unit_type, normalized_name
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION
              '0112 organization-unit normalized identity conflict';
          END IF;
        END $$
        """
    )

    # Keep uq_departments_tenant_slug for legacy slug-based clients. Canonical
    # children use parent-scoped normalized identity and a scoped legacy slug.
    op.create_index(
        "uq_departments_active_root_name",
        "departments",
        ["tenant_id", "unit_type", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL AND is_active"),
    )
    op.create_index(
        "uq_departments_active_child_name",
        "departments",
        ["tenant_id", "parent_id", "unit_type", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NOT NULL AND is_active"),
    )
    op.create_index(
        "uq_departments_tenant_external_key",
        "departments",
        ["tenant_id", "external_key"],
        unique=True,
        postgresql_where=sa.text("external_key IS NOT NULL"),
    )
    op.create_index(
        "ix_departments_tenant_parent_type_active",
        "departments",
        ["tenant_id", "parent_id", "unit_type", "is_active"],
    )

    op.execute(
        r"""
        CREATE FUNCTION validate_organization_unit_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE parent_tenant uuid;
        DECLARE parent_type text;
        DECLARE parent_active boolean;
        DECLARE head_tenant uuid;
        BEGIN
          NEW.name := btrim(NEW.name);
          NEW.normalized_name := lower(
            regexp_replace(btrim(NEW.name), '\s+', ' ', 'g')
          );
          NEW.external_key := NULLIF(btrim(NEW.external_key), '');

          IF NEW.unit_type = 'branch' AND NEW.parent_id IS NOT NULL THEN
            RAISE EXCEPTION 'branch must be a root organization unit'
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.unit_type = 'department' AND NEW.parent_id IS NULL
             AND NOT NEW.legacy_root THEN
            RAISE EXCEPTION 'department requires a branch parent'
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.parent_id = NEW.id THEN
            RAISE EXCEPTION 'organization unit hierarchy cycle'
              USING ERRCODE = 'check_violation';
          END IF;

          IF NEW.parent_id IS NOT NULL THEN
            SELECT tenant_id, unit_type, is_active
              INTO parent_tenant, parent_type, parent_active
              FROM departments
             WHERE id = NEW.parent_id;
            IF parent_tenant IS NULL OR parent_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION 'organization unit parent tenant mismatch'
                USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF NEW.unit_type <> 'department'
               OR parent_type <> 'branch' OR NOT parent_active THEN
              RAISE EXCEPTION 'department parent must be an active branch'
                USING ERRCODE = 'check_violation';
            END IF;
            IF EXISTS (
              WITH RECURSIVE descendants AS (
                SELECT id FROM departments WHERE parent_id = NEW.id
                UNION ALL
                SELECT child.id
                  FROM departments AS child
                  JOIN descendants ON child.parent_id = descendants.id
              )
              SELECT 1 FROM descendants WHERE id = NEW.parent_id
            ) THEN
              RAISE EXCEPTION 'organization unit hierarchy cycle'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;

          IF NEW.head_user_id IS NOT NULL THEN
            SELECT tenant_id INTO head_tenant
              FROM users WHERE id = NEW.head_user_id;
            IF head_tenant IS NULL OR head_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION 'organization unit head tenant mismatch'
                USING ERRCODE = 'foreign_key_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_organization_unit_ownership
        BEFORE INSERT OR UPDATE ON departments
        FOR EACH ROW EXECUTE FUNCTION validate_organization_unit_ownership()
        """
    )

    op.execute("ALTER TABLE departments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE departments FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON departments")
    op.execute("DROP POLICY IF EXISTS tenant_organization_units_isolation ON departments")
    op.execute(
        "CREATE POLICY tenant_organization_units_isolation ON departments "
        "FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("REVOKE ALL ON TABLE departments FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON departments TO lms_app")


def downgrade() -> None:
    op.execute("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM departments
             WHERE source_metadata->>'origin' IS DISTINCT FROM 'legacy_migration'
          ) THEN
            RAISE EXCEPTION
              '0112 downgrade refused: canonical organization-unit data exists';
          END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE departments FORCE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS trg_validate_organization_unit_ownership ON departments")
    op.execute("DROP FUNCTION IF EXISTS validate_organization_unit_ownership()")
    op.execute("DROP POLICY IF EXISTS tenant_organization_units_isolation ON departments")
    op.execute(
        "CREATE POLICY tenant_isolation ON departments FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.drop_index("ix_departments_tenant_parent_type_active", table_name="departments")
    op.drop_index("uq_departments_tenant_external_key", table_name="departments")
    op.drop_index("uq_departments_active_child_name", table_name="departments")
    op.drop_index("uq_departments_active_root_name", table_name="departments")
    op.drop_constraint("ck_departments_source_metadata_object", "departments")
    op.drop_constraint("ck_departments_normalized_name", "departments")
    op.drop_constraint("ck_departments_archive_state", "departments")
    op.drop_constraint("ck_departments_department_parent", "departments")
    op.drop_constraint("ck_departments_branch_root", "departments")
    op.drop_constraint("ck_departments_unit_type", "departments")
    op.drop_column("departments", "legacy_root")
    op.drop_column("departments", "source_metadata")
    op.drop_column("departments", "archived_at")
    op.drop_column("departments", "is_active")
    op.drop_column("departments", "external_key")
    op.drop_column("departments", "normalized_name")
    op.drop_column("departments", "unit_type")
