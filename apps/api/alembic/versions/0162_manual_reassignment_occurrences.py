"""Manual reassignment occurrences preserve predecessor evidence.

Revision ID: 0162
Revises: 0161
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0162"
down_revision = "0161"
branch_labels = None
depends_on = None


def _schema_name() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe manual-reassignment schema")
    return schema


def _table(schema: str, name: str) -> str:
    return f'"{schema}".{name}'


def upgrade() -> None:
    schema = _schema_name()
    enrollments = _table(schema, "enrollments")
    users = _table(schema, "users")
    op.add_column(
        "enrollments",
        sa.Column("previous_enrollment_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=schema,
    )
    op.add_column("enrollments", sa.Column("reassignment_reason", sa.Text(), nullable=True), schema=schema)
    op.add_column(
        "enrollments", sa.Column("reassigned_by", postgresql.UUID(as_uuid=True), nullable=True), schema=schema
    )
    op.add_column("enrollments", sa.Column("reassigned_at", sa.DateTime(timezone=True), nullable=True), schema=schema)
    op.create_foreign_key(
        "fk_enrollments_previous_enrollment",
        "enrollments",
        "enrollments",
        ["previous_enrollment_id"],
        ["id"],
        ondelete="RESTRICT",
        source_schema=schema,
        referent_schema=schema,
    )
    op.create_foreign_key(
        "fk_enrollments_reassigned_by",
        "enrollments",
        "users",
        ["reassigned_by"],
        ["id"],
        ondelete="RESTRICT",
        source_schema=schema,
        referent_schema=schema,
    )
    op.create_index(
        "ix_enrollments_previous_enrollment", "enrollments", ["previous_enrollment_id"], schema=schema
    )
    op.drop_index("uq_enrollments_legacy_active", table_name="enrollments", schema=schema)
    op.create_index(
        "uq_enrollments_current_occurrence",
        "enrollments",
        ["user_id", "course_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('enrolled', 'in_progress') "
            "AND recurring_assignment_id IS NULL "
            "AND learning_path_assignment_id IS NULL"
        ),
        schema=schema,
    )
    op.execute(f"""
        CREATE FUNCTION "{schema}".validate_manual_reassignment_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND ROW(
            NEW.previous_enrollment_id, NEW.reassignment_reason, NEW.reassigned_by,
            NEW.reassigned_at, NEW.source, NEW.tenant_id, NEW.user_id, NEW.course_id
          ) IS DISTINCT FROM ROW(
            OLD.previous_enrollment_id, OLD.reassignment_reason, OLD.reassigned_by,
            OLD.reassigned_at, OLD.source, OLD.tenant_id, OLD.user_id, OLD.course_id
          ) THEN
            RAISE EXCEPTION 'manual reassignment identity is immutable';
          END IF;
          IF TG_OP = 'UPDATE' THEN RETURN NEW; END IF;
          IF NEW.previous_enrollment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM {enrollments} predecessor
             WHERE predecessor.id = NEW.previous_enrollment_id
               AND predecessor.tenant_id = NEW.tenant_id
               AND predecessor.user_id = NEW.user_id
               AND predecessor.course_id = NEW.course_id
          ) THEN RAISE EXCEPTION 'manual reassignment predecessor ownership mismatch'; END IF;
          IF NEW.previous_enrollment_id = NEW.id THEN
            RAISE EXCEPTION 'manual reassignment predecessor cannot reference itself';
          END IF;
          IF NEW.reassigned_by IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM {users} actor
             WHERE actor.id = NEW.reassigned_by
               AND actor.tenant_id = NEW.tenant_id
               AND actor.role = 'methodologist'
          ) THEN RAISE EXCEPTION 'manual reassignment actor ownership mismatch'; END IF;
          IF NEW.previous_enrollment_id IS NOT NULL AND (
            NEW.source <> 'manual' OR NEW.reassignment_reason IS NULL
            OR btrim(NEW.reassignment_reason) = '' OR NEW.reassigned_by IS NULL
            OR NEW.reassigned_at IS NULL
          ) THEN
            RAISE EXCEPTION 'manual reassignment audit fields required';
          END IF;
          IF NEW.previous_enrollment_id IS NULL AND (
            NEW.reassignment_reason IS NOT NULL OR NEW.reassigned_by IS NOT NULL
            OR NEW.reassigned_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'manual reassignment audit fields require a predecessor';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        f'CREATE TRIGGER trg_validate_manual_reassignment_identity '
        f'BEFORE INSERT OR UPDATE ON {enrollments} FOR EACH ROW '
        f'EXECUTE FUNCTION "{schema}".validate_manual_reassignment_identity()'
    )
    # enrollments is already tenant-scoped and RLS/FORCE RLS remains enabled;
    # this migration adds no table or policy that could widen runtime access.
    op.execute(f"ALTER TABLE {enrollments} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    schema = _schema_name()
    enrollments = _table(schema, "enrollments")
    op.execute(f"""
        DO $$ BEGIN IF EXISTS (SELECT 1 FROM {enrollments} WHERE previous_enrollment_id IS NOT NULL) THEN
          RAISE EXCEPTION '0162 downgrade refused: reassignment history exists';
        END IF; END $$
    """)
    op.execute(f"DROP TRIGGER IF EXISTS trg_validate_manual_reassignment_identity ON {enrollments}")
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".validate_manual_reassignment_identity()')
    op.drop_index("uq_enrollments_current_occurrence", table_name="enrollments", schema=schema)
    op.create_index(
        "uq_enrollments_legacy_active", "enrollments", ["user_id", "course_id", "tenant_id"], unique=True,
        postgresql_where=sa.text(
            "status IN ('enrolled','completed') "
            "AND recurring_assignment_id IS NULL "
            "AND learning_path_assignment_id IS NULL"
        ),
        schema=schema,
    )
    op.drop_index("ix_enrollments_previous_enrollment", table_name="enrollments", schema=schema)
    op.drop_constraint(
        "fk_enrollments_reassigned_by", "enrollments", type_="foreignkey", schema=schema
    )
    op.drop_constraint(
        "fk_enrollments_previous_enrollment", "enrollments", type_="foreignkey", schema=schema
    )
    op.drop_column("enrollments", "reassigned_at", schema=schema)
    op.drop_column("enrollments", "reassigned_by", schema=schema)
    op.drop_column("enrollments", "reassignment_reason", schema=schema)
    op.drop_column("enrollments", "previous_enrollment_id", schema=schema)
