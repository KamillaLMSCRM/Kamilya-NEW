"""Explicit responsible user for employee groups.

Revision ID: 0164
Revises: 0163
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0164"
down_revision = "0163"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe training responsibility schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    op.add_column(
        "cohorts",
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=schema,
    )
    op.create_foreign_key(
        "fk_cohorts_responsible_user_id",
        "cohorts",
        "users",
        ["responsible_user_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cohorts_responsible_user_id",
        "cohorts",
        ["responsible_user_id"],
        schema=schema,
    )
    op.execute(f"""
        CREATE FUNCTION "{schema}".validate_cohort_responsible_user()
        RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
        DECLARE responsible_tenant uuid;
        DECLARE responsible_role text;
        DECLARE responsible_active boolean;
        DECLARE responsible_status text;
        BEGIN
          IF NEW.responsible_user_id IS NOT NULL THEN
            SELECT tenant_id, role, is_active, status
              INTO responsible_tenant, responsible_role, responsible_active, responsible_status
              FROM "{schema}".users WHERE id = NEW.responsible_user_id;
            IF responsible_tenant IS NULL OR responsible_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION 'cohort responsible user tenant mismatch'
                USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF responsible_role <> 'methodologist'
              OR responsible_active IS NOT TRUE
              OR responsible_status <> 'active' THEN
              RAISE EXCEPTION 'cohort responsible user must be active methodologist'
                USING ERRCODE = 'foreign_key_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute(f"""
        CREATE TRIGGER trg_validate_cohort_responsible_user
        BEFORE INSERT OR UPDATE OF tenant_id,responsible_user_id ON "{schema}".cohorts
        FOR EACH ROW EXECUTE FUNCTION "{schema}".validate_cohort_responsible_user();
    """)


def downgrade() -> None:
    schema = _schema()
    op.execute(
        f'DROP TRIGGER IF EXISTS trg_validate_cohort_responsible_user ON "{schema}".cohorts'
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".validate_cohort_responsible_user()')
    op.drop_index("ix_cohorts_responsible_user_id", table_name="cohorts", schema=schema)
    op.drop_constraint(
        "fk_cohorts_responsible_user_id",
        "cohorts",
        type_="foreignkey",
        schema=schema,
    )
    op.drop_column("cohorts", "responsible_user_id", schema=schema)
