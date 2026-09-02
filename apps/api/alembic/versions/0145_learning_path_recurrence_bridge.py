"""Align LearningPath recurrence identities with the ORM/API bridge.

Revision ID: 0145
Revises: 0144

The preceding 0143 migration introduced the partial identities, but older
ORM metadata still described unconditional assignment and course-rule keys.
This migration is intentionally additive/idempotent for databases already at
0143 and never disables row-level security.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0145"
down_revision = "0144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'learning_path_assignments'::regclass
              AND conname = 'uq_learning_path_assignment_path_user'
          ) THEN
            ALTER TABLE learning_path_assignments
              DROP CONSTRAINT uq_learning_path_assignment_path_user;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_path_assignment_path_user_legacy
        ON learning_path_assignments (tenant_id, path_id, user_id)
        WHERE recurrence_instance_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_path_assignment_recurrence_instance
        ON learning_path_assignments (tenant_id, recurrence_instance_id)
        WHERE recurrence_instance_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_rule_course_user
        ON recurring_learning_rules (tenant_id, course_id, user_id)
        WHERE course_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_rule_learning_path_user
        ON recurring_learning_rules (tenant_id, learning_path_id, user_id)
        WHERE learning_path_id IS NOT NULL
        """
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "DROP CONSTRAINT IF EXISTS ck_learning_path_assignment_source"
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "ADD CONSTRAINT ck_learning_path_assignment_source "
        "CHECK (source IN ('manual', 'cohort', 'department', 'position', 'recurring'))"
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "DROP CONSTRAINT IF EXISTS ck_learning_path_assignment_recurrence_source"
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "ADD CONSTRAINT ck_learning_path_assignment_recurrence_source "
        "CHECK (recurrence_instance_id IS NULL OR source = 'recurring')"
    )
    op.execute(
        "ALTER TABLE recurring_learning_rules "
        "DROP CONSTRAINT IF EXISTS ck_recurring_rule_due"
    )
    op.execute(
        "ALTER TABLE recurring_learning_rules "
        "ADD CONSTRAINT ck_recurring_rule_due "
        "CHECK (due_days BETWEEN 0 AND 3650)"
    )
    op.execute(
        "ALTER TABLE recurring_learning_rules "
        "DROP CONSTRAINT IF EXISTS ck_recurring_rule_due_not_after_cadence"
    )
    op.execute(
        "ALTER TABLE recurring_learning_rules "
        "ADD CONSTRAINT ck_recurring_rule_due_not_after_cadence "
        "CHECK (due_days <= cadence_days)"
    )
    op.add_column(
        "enrollments",
        sa.Column("learning_path_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_enrollments_learning_path_assignment",
        "enrollments",
        "learning_path_assignments",
        ["learning_path_assignment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("uq_enrollments_legacy_active", table_name="enrollments")
    op.create_index(
        "uq_enrollments_legacy_active",
        "enrollments",
        ["user_id", "course_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('enrolled','completed') "
            "AND recurring_assignment_id IS NULL "
            "AND learning_path_assignment_id IS NULL"
        ),
    )
    op.create_index(
        "uq_enrollments_learning_path_assignment_course",
        "enrollments",
        ["tenant_id", "learning_path_assignment_id", "course_id"],
        unique=True,
        postgresql_where=sa.text("learning_path_assignment_id IS NOT NULL"),
    )
    op.execute(
        """
        ALTER TABLE enrollments
          ADD CONSTRAINT ck_enrollments_one_recurrence_identity
          CHECK (NOT (recurring_assignment_id IS NOT NULL AND learning_path_assignment_id IS NOT NULL));
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_recurring_enrollment_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NEW.recurring_assignment_id IS NOT NULL
             AND NEW.learning_path_assignment_id IS NOT NULL THEN
            RAISE EXCEPTION 'enrollment cannot reference course and learning-path recurrence identities';
          END IF;
          IF NEW.recurring_assignment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM recurring_learning_assignments a
            WHERE a.id=NEW.recurring_assignment_id AND a.tenant_id=NEW.tenant_id
              AND a.user_id=NEW.user_id AND a.course_id=NEW.course_id
          ) THEN
            RAISE EXCEPTION 'recurring enrollment ownership mismatch';
          END IF;
          IF NEW.learning_path_assignment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM learning_path_assignments a
            JOIN learning_path_courses pc ON pc.path_id = a.path_id
            WHERE a.id=NEW.learning_path_assignment_id
              AND a.tenant_id=NEW.tenant_id
              AND a.user_id=NEW.user_id
              AND pc.course_id=NEW.course_id
          ) THEN
            RAISE EXCEPTION 'learning-path enrollment ownership mismatch';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    # Reassert, rather than weaken, the existing tenant boundary.
    op.execute("ALTER TABLE learning_path_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE learning_path_assignments FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recurring_learning_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recurring_learning_rules FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM learning_path_assignments
            WHERE source = 'recurring' OR recurrence_instance_id IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM enrollments WHERE learning_path_assignment_id IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM recurring_learning_rules WHERE due_days > 365
          ) THEN
            RAISE EXCEPTION '0145 downgrade refused: recurrence bridge data exists';
          END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_validate_recurring_enrollment_identity ON enrollments")
    op.execute("DROP FUNCTION IF EXISTS validate_recurring_enrollment_identity()")
    op.execute(
        """
        CREATE FUNCTION validate_recurring_enrollment_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NEW.recurring_assignment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM recurring_learning_assignments a
            WHERE a.id=NEW.recurring_assignment_id AND a.tenant_id=NEW.tenant_id
              AND a.user_id=NEW.user_id AND a.course_id=NEW.course_id
          ) THEN
            RAISE EXCEPTION 'recurring enrollment ownership mismatch';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_recurring_enrollment_identity
        BEFORE INSERT OR UPDATE ON enrollments FOR EACH ROW
        EXECUTE FUNCTION validate_recurring_enrollment_identity()
        """
    )
    op.drop_constraint("ck_enrollments_one_recurrence_identity", "enrollments", type="check")
    op.drop_index("uq_enrollments_learning_path_assignment_course", table_name="enrollments")
    op.drop_index("uq_enrollments_legacy_active", table_name="enrollments")
    op.create_index(
        "uq_enrollments_legacy_active",
        "enrollments",
        ["user_id", "course_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('enrolled','completed') AND recurring_assignment_id IS NULL"),
    )
    op.drop_constraint("fk_enrollments_learning_path_assignment", "enrollments", type="foreignkey")
    op.drop_column("enrollments", "learning_path_assignment_id")
    op.drop_constraint("ck_recurring_rule_due_not_after_cadence", "recurring_learning_rules", type="check")
    op.drop_constraint("ck_recurring_rule_due", "recurring_learning_rules", type="check")
    op.create_check_constraint(
        "ck_recurring_rule_due",
        "recurring_learning_rules",
        "due_days BETWEEN 0 AND 365",
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "DROP CONSTRAINT IF EXISTS ck_learning_path_assignment_source"
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "DROP CONSTRAINT IF EXISTS ck_learning_path_assignment_recurrence_source"
    )
    op.execute(
        "ALTER TABLE learning_path_assignments "
        "ADD CONSTRAINT ck_learning_path_assignment_source "
        "CHECK (source IN ('manual', 'cohort', 'department', 'position'))"
    )
