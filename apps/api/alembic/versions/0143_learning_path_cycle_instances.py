"""Add recurring LearningPath cycle instances and idempotent assignment linkage.

Revision ID: 0143
Revises: 0142
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0143"
down_revision = "0142"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.alter_column("recurring_learning_rules", "course_id", nullable=True)
    op.add_column("recurring_learning_rules", sa.Column("learning_path_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_recurring_rule_learning_path", "recurring_learning_rules", "learning_paths", ["learning_path_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_recurring_rule_exactly_one_target", "recurring_learning_rules", "(course_id IS NOT NULL AND learning_path_id IS NULL) OR (course_id IS NULL AND learning_path_id IS NOT NULL)")
    op.drop_constraint("uq_recurring_rule_course_user", "recurring_learning_rules", type_="unique")
    op.create_index("uq_recurring_rule_course_user", "recurring_learning_rules", ["tenant_id", "course_id", "user_id"], unique=True, postgresql_where=sa.text("course_id IS NOT NULL"))
    op.create_index("uq_recurring_rule_learning_path_user", "recurring_learning_rules", ["tenant_id", "learning_path_id", "user_id"], unique=True, postgresql_where=sa.text("learning_path_id IS NOT NULL"))

    op.create_table(
        "learning_path_cycle_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["recurring_learning_rules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["path_id"], ["learning_paths.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "rule_id", "sequence_no", name="uq_learning_path_cycle_instance_occurrence"),
        sa.CheckConstraint("sequence_no >= 1", name="ck_learning_path_cycle_instance_sequence"),
        sa.CheckConstraint("status IN ('scheduled', 'active', 'completed', 'skipped', 'cancelled')", name="ck_learning_path_cycle_instance_status"),
        sa.CheckConstraint("due_at IS NULL OR starts_at IS NULL OR due_at >= starts_at", name="ck_learning_path_cycle_instance_dates"),
        sa.CheckConstraint("(status = 'completed' AND completed_at IS NOT NULL) OR (status <> 'completed' AND completed_at IS NULL)", name="ck_learning_path_cycle_instance_completion"),
    )
    op.create_index("ix_learning_path_cycle_instances_tenant_schedule", "learning_path_cycle_instances", ["tenant_id", "scheduled_for"])
    op.create_index("ix_learning_path_cycle_instances_tenant_user", "learning_path_cycle_instances", ["tenant_id", "user_id", "scheduled_for"])
    op.add_column("learning_path_assignments", sa.Column("recurrence_instance_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_learning_path_assignment_recurrence_instance", "learning_path_assignments", "learning_path_cycle_instances", ["recurrence_instance_id"], ["id"], ondelete="RESTRICT")
    op.drop_constraint("uq_learning_path_assignment_path_user", "learning_path_assignments", type_="unique")
    op.create_index("uq_learning_path_assignment_path_user_legacy", "learning_path_assignments", ["tenant_id", "path_id", "user_id"], unique=True, postgresql_where=sa.text("recurrence_instance_id IS NULL"))
    op.create_index("uq_learning_path_assignment_recurrence_instance", "learning_path_assignments", ["tenant_id", "recurrence_instance_id"], unique=True, postgresql_where=sa.text("recurrence_instance_id IS NOT NULL"))

    for table in ("learning_path_cycle_instances",):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} FOR ALL TO lms_app USING ({TENANT}) WITH CHECK ({TENANT})")
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app")

    # Extend the pre-existing rule ownership guard without changing the
    # semantics of legacy course-based rules.
    op.execute("CREATE OR REPLACE FUNCTION validate_recurring_learning_rule_ownership() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN IF (NEW.course_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM courses c WHERE c.id=NEW.course_id AND c.tenant_id=NEW.tenant_id)) OR (NEW.learning_path_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM learning_paths p WHERE p.id=NEW.learning_path_id AND p.tenant_id=NEW.tenant_id)) OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id AND (u.role='student' OR EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=u.id AND ur.tenant_id=NEW.tenant_id AND ur.role='student'))) OR (NEW.created_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users a WHERE a.id=NEW.created_by AND a.tenant_id=NEW.tenant_id)) THEN RAISE EXCEPTION 'recurring learning rule tenant ownership mismatch'; END IF; RETURN NEW; END $$")
    op.execute("ALTER TABLE learning_path_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE learning_path_assignments FORCE ROW LEVEL SECURITY")
    op.execute("CREATE OR REPLACE FUNCTION validate_learning_path_cycle_ownership() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN IF NOT EXISTS (SELECT 1 FROM recurring_learning_rules r WHERE r.id=NEW.rule_id AND r.tenant_id=NEW.tenant_id AND r.learning_path_id=NEW.path_id AND r.user_id=NEW.user_id) OR NOT EXISTS (SELECT 1 FROM learning_paths p WHERE p.id=NEW.path_id AND p.tenant_id=NEW.tenant_id) OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id) THEN RAISE EXCEPTION 'learning path cycle instance tenant ownership mismatch'; END IF; RETURN NEW; END $$")
    op.execute("CREATE TRIGGER trg_validate_learning_path_cycle_ownership BEFORE INSERT OR UPDATE ON learning_path_cycle_instances FOR EACH ROW EXECUTE FUNCTION validate_learning_path_cycle_ownership()")
    op.execute("CREATE OR REPLACE FUNCTION validate_learning_path_assignment_recurrence_ownership() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN IF NEW.recurrence_instance_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM learning_path_cycle_instances i WHERE i.id=NEW.recurrence_instance_id AND i.tenant_id=NEW.tenant_id AND i.path_id=NEW.path_id AND i.user_id=NEW.user_id) THEN RAISE EXCEPTION 'learning path assignment recurrence instance tenant ownership mismatch'; END IF; RETURN NEW; END $$")
    op.execute("CREATE TRIGGER trg_validate_learning_path_assignment_recurrence_ownership BEFORE INSERT OR UPDATE ON learning_path_assignments FOR EACH ROW EXECUTE FUNCTION validate_learning_path_assignment_recurrence_ownership()")


def downgrade() -> None:
    op.execute("ALTER TABLE learning_path_cycle_instances NO FORCE ROW LEVEL SECURITY")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM learning_path_cycle_instances) OR EXISTS (SELECT 1 FROM learning_path_assignments WHERE recurrence_instance_id IS NOT NULL) THEN RAISE EXCEPTION '0143 downgrade refused: cycle instances or linked assignments exist'; END IF; END $$")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_learning_path_assignment_recurrence_ownership ON learning_path_assignments")
    op.execute("DROP FUNCTION IF EXISTS validate_learning_path_assignment_recurrence_ownership()")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_learning_path_cycle_ownership ON learning_path_cycle_instances")
    op.execute("DROP FUNCTION IF EXISTS validate_learning_path_cycle_ownership()")
    op.drop_constraint("fk_learning_path_assignment_recurrence_instance", "learning_path_assignments", type_="foreignkey")
    op.drop_index("uq_learning_path_assignment_recurrence_instance", table_name="learning_path_assignments")
    op.drop_index("uq_learning_path_assignment_path_user_legacy", table_name="learning_path_assignments")
    op.drop_column("learning_path_assignments", "recurrence_instance_id")
    op.drop_index("ix_learning_path_cycle_instances_tenant_user", table_name="learning_path_cycle_instances")
    op.drop_index("ix_learning_path_cycle_instances_tenant_schedule", table_name="learning_path_cycle_instances")
    op.drop_table("learning_path_cycle_instances")
    op.drop_index("uq_recurring_rule_learning_path_user", table_name="recurring_learning_rules")
    op.drop_index("uq_recurring_rule_course_user", table_name="recurring_learning_rules")
    op.drop_constraint("ck_recurring_rule_exactly_one_target", "recurring_learning_rules", type_="check")
    op.drop_constraint("fk_recurring_rule_learning_path", "recurring_learning_rules", type_="foreignkey")
    op.drop_column("recurring_learning_rules", "learning_path_id")
    op.alter_column("recurring_learning_rules", "course_id", nullable=False)
    op.create_unique_constraint("uq_recurring_rule_course_user", "recurring_learning_rules", ["tenant_id", "course_id", "user_id"])
    op.execute("CREATE OR REPLACE FUNCTION validate_recurring_learning_rule_ownership() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN IF NOT EXISTS (SELECT 1 FROM courses c WHERE c.id=NEW.course_id AND c.tenant_id=NEW.tenant_id) OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.user_id AND u.tenant_id=NEW.tenant_id AND (u.role='student' OR EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=u.id AND ur.tenant_id=NEW.tenant_id AND ur.role='student'))) OR (NEW.created_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users a WHERE a.id=NEW.created_by AND a.tenant_id=NEW.tenant_id)) THEN RAISE EXCEPTION 'recurring learning rule tenant ownership mismatch'; END IF; RETURN NEW; END $$")
