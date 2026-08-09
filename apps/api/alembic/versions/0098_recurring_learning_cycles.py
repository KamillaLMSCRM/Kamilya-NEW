"""Recurring learning rules and immutable assignments. Revision ID: 0098; Revises: 0097."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None
TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade():
    op.create_table(
        "recurring_learning_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "course_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("cadence_days", sa.Integer(), nullable=False),
        sa.Column("due_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("cadence_days BETWEEN 1 AND 3660", name="ck_recurring_rule_cadence"),
        sa.CheckConstraint("due_days BETWEEN 0 AND 365", name="ck_recurring_rule_due"),
        sa.CheckConstraint("status IN ('draft','active','inactive')", name="ck_recurring_rule_status"),
        sa.UniqueConstraint("tenant_id", "course_id", "user_id", name="uq_recurring_rule_course_user"),
    )
    op.create_table(
        "recurring_learning_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recurring_learning_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "course_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("enrollments.id", ondelete="RESTRICT")),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="assigned"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('assigned','completed','skipped')", name="ck_recurring_assignment_status"),
        sa.UniqueConstraint("rule_id", "scheduled_for", name="uq_recurring_assignment_run"),
    )
    for table in ("recurring_learning_rules", "recurring_learning_assignments"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL TO lms_app USING ({TENANT}) WITH CHECK ({TENANT})"
        )
        op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO lms_app")
    op.execute(
        """
        CREATE FUNCTION validate_recurring_learning_rule_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM courses c WHERE c.id=NEW.course_id AND c.tenant_id=NEW.tenant_id)
             OR NOT EXISTS (
                 SELECT 1 FROM users u
                 WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id
                   AND (u.role='student' OR EXISTS (
                       SELECT 1 FROM user_roles ur
                       WHERE ur.user_id=u.id AND ur.tenant_id=NEW.tenant_id AND ur.role='student'
                   ))
             )
             OR (NEW.created_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users a WHERE a.id=NEW.created_by AND a.tenant_id=NEW.tenant_id))
          THEN RAISE EXCEPTION 'recurring learning rule tenant ownership mismatch'; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_recurring_learning_rule_ownership
        BEFORE INSERT OR UPDATE ON recurring_learning_rules
        FOR EACH ROW EXECUTE FUNCTION validate_recurring_learning_rule_ownership()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_recurring_learning_assignment_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM recurring_learning_rules r WHERE r.id=NEW.rule_id AND r.tenant_id=NEW.tenant_id AND r.user_id=NEW.user_id AND r.course_id=NEW.course_id)
             OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id)
             OR NOT EXISTS (SELECT 1 FROM courses c WHERE c.id=NEW.course_id AND c.tenant_id=NEW.tenant_id)
             OR (NEW.enrollment_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM enrollments e WHERE e.id=NEW.enrollment_id AND e.tenant_id=NEW.tenant_id AND e.user_id=NEW.user_id AND e.course_id=NEW.course_id))
          THEN RAISE EXCEPTION 'recurring learning assignment tenant ownership mismatch'; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_recurring_learning_assignment_ownership
        BEFORE INSERT OR UPDATE ON recurring_learning_assignments
        FOR EACH ROW EXECUTE FUNCTION validate_recurring_learning_assignment_ownership()
        """
    )


def downgrade():
    # The owner must see all tenants while checking the destructive downgrade.
    # If the guard raises, the transaction restores FORCE RLS automatically.
    op.execute("ALTER TABLE recurring_learning_rules NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recurring_learning_assignments NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM recurring_learning_rules LIMIT 1)
             OR EXISTS (SELECT 1 FROM recurring_learning_assignments LIMIT 1) THEN
            RAISE EXCEPTION 'refusing downgrade: recurring learning rules or history exist';
          END IF;
        END $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_validate_recurring_learning_assignment_ownership ON recurring_learning_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_recurring_learning_assignment_ownership()")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_recurring_learning_rule_ownership ON recurring_learning_rules")
    op.execute("DROP FUNCTION IF EXISTS validate_recurring_learning_rule_ownership()")
    for table in ("recurring_learning_assignments", "recurring_learning_rules"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
