"""Cycle-specific enrollment, progress and certificate identity.

Revision ID: 0103
Revises: 0102
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrollments",
        sa.Column(
            "recurring_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recurring_learning_assignments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "progress",
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "certificates",
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.drop_index("uq_enrollments_user_course_tenant", table_name="enrollments")
    op.create_index(
        "uq_enrollments_legacy_active",
        "enrollments",
        ["user_id", "course_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('enrolled','completed') AND recurring_assignment_id IS NULL"),
    )
    op.create_index(
        "uq_enrollments_recurring_assignment",
        "enrollments",
        ["tenant_id", "recurring_assignment_id"],
        unique=True,
        postgresql_where=sa.text("recurring_assignment_id IS NOT NULL"),
    )
    op.drop_index("uq_progress_tenant_user_lesson", table_name="progress")
    op.create_index(
        "uq_progress_legacy_lesson",
        "progress",
        ["tenant_id", "user_id", "lesson_id"],
        unique=True,
        postgresql_where=sa.text("enrollment_id IS NULL"),
    )
    op.create_index(
        "uq_progress_enrollment_lesson",
        "progress",
        ["tenant_id", "enrollment_id", "lesson_id"],
        unique=True,
        postgresql_where=sa.text("enrollment_id IS NOT NULL"),
    )
    op.create_index(
        "uq_certificates_enrollment",
        "certificates",
        ["tenant_id", "enrollment_id"],
        unique=True,
        postgresql_where=sa.text("enrollment_id IS NOT NULL"),
    )
    # Production drift reconciliation did not preserve this early index in
    # every environment; IF EXISTS keeps the additive upgrade portable.
    op.execute("DROP INDEX IF EXISTS ix_certificates_user_course")
    op.create_index(
        "uq_certificates_legacy_user_course",
        "certificates",
        ["user_id", "course_id"],
        unique=True,
        postgresql_where=sa.text("enrollment_id IS NULL"),
    )
    statements = (
        """
        CREATE FUNCTION validate_recurring_enrollment_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NEW.recurring_assignment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM recurring_learning_assignments a
            WHERE a.id=NEW.recurring_assignment_id AND a.tenant_id=NEW.tenant_id
              AND a.user_id=NEW.user_id AND a.course_id=NEW.course_id
          ) THEN RAISE EXCEPTION 'recurring enrollment ownership mismatch'; END IF;
          RETURN NEW;
        END $$
        """,
        """
        CREATE TRIGGER trg_validate_recurring_enrollment_identity
        BEFORE INSERT OR UPDATE ON enrollments FOR EACH ROW
        EXECUTE FUNCTION validate_recurring_enrollment_identity()
        """,
        """
        CREATE FUNCTION validate_progress_enrollment_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NEW.enrollment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM enrollments e WHERE e.id=NEW.enrollment_id
              AND e.tenant_id=NEW.tenant_id AND e.user_id=NEW.user_id
              AND e.course_id=NEW.course_id
          ) THEN RAISE EXCEPTION 'progress enrollment ownership mismatch'; END IF;
          RETURN NEW;
        END $$
        """,
        """
        CREATE TRIGGER trg_validate_progress_enrollment_identity
        BEFORE INSERT OR UPDATE ON progress FOR EACH ROW
        EXECUTE FUNCTION validate_progress_enrollment_identity()
        """,
        """
        CREATE FUNCTION validate_certificate_enrollment_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NEW.enrollment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM enrollments e WHERE e.id=NEW.enrollment_id
              AND e.tenant_id=NEW.tenant_id AND e.user_id=NEW.user_id
              AND e.course_id=NEW.course_id AND e.status='completed'
          ) THEN RAISE EXCEPTION 'certificate enrollment ownership mismatch'; END IF;
          RETURN NEW;
        END $$
        """,
        """
        CREATE TRIGGER trg_validate_certificate_enrollment_identity
        BEFORE INSERT OR UPDATE ON certificates FOR EACH ROW
        EXECUTE FUNCTION validate_certificate_enrollment_identity()
        """,
    )
    for statement in statements:
        op.execute(statement)
    op.create_index("ix_recurring_rules_due", "recurring_learning_rules", ["status", "next_run_at"])
    op.execute(
        """CREATE FUNCTION due_recurring_learning_rules(p_limit integer DEFAULT 20)
        RETURNS TABLE(id uuid,tenant_id uuid) LANGUAGE sql SECURITY DEFINER
        SET search_path=public,pg_temp AS $$
        SELECT id,tenant_id FROM recurring_learning_rules
        WHERE status='active' AND next_run_at<=now()
        ORDER BY next_run_at,id LIMIT greatest(1,least(p_limit,100)) $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION due_recurring_learning_rules(integer) FROM PUBLIC, lms_app")
    op.execute("GRANT EXECUTE ON FUNCTION due_recurring_learning_rules(integer) TO lms_recovery")


def downgrade() -> None:
    op.execute("ALTER TABLE enrollments NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """DO $$ BEGIN IF EXISTS (
        SELECT 1 FROM enrollments WHERE recurring_assignment_id IS NOT NULL
        ) THEN RAISE EXCEPTION '0103 downgrade refused: recurring enrollments exist'; END IF; END $$"""
    )
    op.execute("ALTER TABLE enrollments FORCE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS due_recurring_learning_rules(integer)")
    op.drop_index("ix_recurring_rules_due", table_name="recurring_learning_rules")
    for table, trigger, function in (
        ("certificates", "trg_validate_certificate_enrollment_identity", "validate_certificate_enrollment_identity"),
        ("progress", "trg_validate_progress_enrollment_identity", "validate_progress_enrollment_identity"),
        ("enrollments", "trg_validate_recurring_enrollment_identity", "validate_recurring_enrollment_identity"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")
    op.drop_index("uq_certificates_enrollment", table_name="certificates")
    op.drop_index("uq_certificates_legacy_user_course", table_name="certificates")
    op.create_index("ix_certificates_user_course", "certificates", ["user_id", "course_id"], unique=True)
    op.drop_index("uq_progress_enrollment_lesson", table_name="progress")
    op.drop_index("uq_progress_legacy_lesson", table_name="progress")
    op.create_index("uq_progress_tenant_user_lesson", "progress", ["tenant_id", "user_id", "lesson_id"], unique=True)
    op.drop_index("uq_enrollments_recurring_assignment", table_name="enrollments")
    op.drop_index("uq_enrollments_legacy_active", table_name="enrollments")
    op.create_index(
        "uq_enrollments_user_course_tenant",
        "enrollments",
        ["user_id", "course_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('enrolled', 'completed')"),
    )
    op.drop_column("certificates", "enrollment_id")
    op.drop_column("progress", "enrollment_id")
    op.drop_column("enrollments", "recurring_assignment_id")
