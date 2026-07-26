"""Add immutable learning-program versions and learner assignments.

Revision ID: 0075
Revises: 0074
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("learning_paths", sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "learning_paths",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "learning_paths",
        sa.Column("sequencing_mode", sa.Text(), nullable=False, server_default="linear"),
    )
    op.add_column("learning_paths", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("learning_paths", sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True))

    # Existing rows become the first immutable version of their own family.
    op.execute("UPDATE learning_paths SET family_id = id WHERE family_id IS NULL")
    op.execute("UPDATE learning_paths SET published_at = created_at WHERE status = 'published' AND published_at IS NULL")
    op.alter_column("learning_paths", "family_id", nullable=False)
    op.create_check_constraint(
        "ck_learning_path_sequencing_mode",
        "learning_paths",
        "sequencing_mode IN ('linear', 'open')",
    )
    op.create_foreign_key(
        "fk_learning_paths_supersedes_id",
        "learning_paths",
        "learning_paths",
        ["supersedes_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_learning_path_family_version",
        "learning_paths",
        ["tenant_id", "family_id", "version"],
    )
    op.create_index("ix_learning_paths_family_id", "learning_paths", ["family_id"])
    op.create_index("ix_learning_paths_published_at", "learning_paths", ["tenant_id", "published_at"])

    op.create_table(
        "learning_path_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "path_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("source_ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source IN ('manual', 'cohort', 'department', 'position')",
            name="ck_learning_path_assignment_source",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled', 'completed')",
            name="ck_learning_path_assignment_status",
        ),
        sa.CheckConstraint(
            "due_at IS NULL OR starts_at IS NULL OR due_at >= starts_at",
            name="ck_learning_path_assignment_dates",
        ),
        sa.UniqueConstraint("path_id", "user_id", name="uq_learning_path_assignment_path_user"),
    )
    op.create_index("ix_learning_path_assignments_tenant", "learning_path_assignments", ["tenant_id"])
    op.create_index("ix_learning_path_assignments_path", "learning_path_assignments", ["path_id"])
    op.create_index("ix_learning_path_assignments_user", "learning_path_assignments", ["user_id"])
    op.create_index(
        "ix_learning_path_assignments_active_user",
        "learning_path_assignments",
        ["tenant_id", "user_id", "starts_at"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # Protect snapshots even if a future endpoint bypasses the API's draft
    # guard. Curriculum rows resolve their parent tenant through the existing
    # RLS policy, so the trigger preserves the same ownership boundary.
    op.execute(
        """
        CREATE FUNCTION prevent_published_learning_path_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'published' THEN
                RAISE EXCEPTION 'Published learning-program versions are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER learning_paths_prevent_published_mutation
        BEFORE UPDATE OR DELETE ON learning_paths
        FOR EACH ROW EXECUTE FUNCTION prevent_published_learning_path_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_published_learning_path_step_mutation()
        RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
            SELECT status INTO parent_status
            FROM learning_paths
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.path_id ELSE NEW.path_id END;
            IF parent_status = 'published' THEN
                RAISE EXCEPTION 'Published learning-program curriculum is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER learning_path_courses_prevent_published_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON learning_path_courses
        FOR EACH ROW EXECUTE FUNCTION prevent_published_learning_path_step_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_learning_path_assignment_parent()
        RETURNS trigger AS $$
        DECLARE path_tenant uuid;
        DECLARE path_status text;
        DECLARE learner_tenant uuid;
        DECLARE assigner_tenant uuid;
        BEGIN
            SELECT tenant_id, status INTO path_tenant, path_status
            FROM learning_paths
            WHERE id = NEW.path_id;
            IF path_tenant IS NULL OR path_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Learning-program assignment path must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF path_status <> 'published' THEN
                RAISE EXCEPTION 'Learning-program assignments require a published version'
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT tenant_id INTO learner_tenant
            FROM users
            WHERE id = NEW.user_id;
            IF learner_tenant IS NULL OR learner_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Learning-program assignment learner must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF NEW.assigned_by IS NOT NULL THEN
                SELECT tenant_id INTO assigner_tenant
                FROM users
                WHERE id = NEW.assigned_by;
                IF assigner_tenant IS NULL OR assigner_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Learning-program assignment author must belong to the same tenant'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER learning_path_assignments_validate_parent
        BEFORE INSERT OR UPDATE OF path_id, tenant_id, user_id, assigned_by ON learning_path_assignments
        FOR EACH ROW EXECUTE FUNCTION validate_learning_path_assignment_parent();
        """
    )

    op.execute("ALTER TABLE learning_path_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE learning_path_assignments FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON learning_path_assignments
        FOR ALL TO lms_app
        USING ({TENANT_EXPR})
        WITH CHECK ({TENANT_EXPR})
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON learning_path_assignments TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON learning_path_assignments")
    op.execute("DROP TRIGGER IF EXISTS learning_path_assignments_validate_parent ON learning_path_assignments")
    op.execute("DROP FUNCTION IF EXISTS validate_learning_path_assignment_parent()")
    op.execute("DROP TRIGGER IF EXISTS learning_path_courses_prevent_published_mutation ON learning_path_courses")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_learning_path_step_mutation()")
    op.execute("DROP TRIGGER IF EXISTS learning_paths_prevent_published_mutation ON learning_paths")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_learning_path_mutation()")
    op.drop_index("ix_learning_path_assignments_active_user", table_name="learning_path_assignments")
    op.drop_index("ix_learning_path_assignments_user", table_name="learning_path_assignments")
    op.drop_index("ix_learning_path_assignments_path", table_name="learning_path_assignments")
    op.drop_index("ix_learning_path_assignments_tenant", table_name="learning_path_assignments")
    op.drop_table("learning_path_assignments")
    op.drop_index("ix_learning_paths_published_at", table_name="learning_paths")
    op.drop_index("ix_learning_paths_family_id", table_name="learning_paths")
    op.drop_constraint("uq_learning_path_family_version", "learning_paths", type_="unique")
    op.drop_constraint("fk_learning_paths_supersedes_id", "learning_paths", type_="foreignkey")
    op.drop_constraint("ck_learning_path_sequencing_mode", "learning_paths", type_="check")
    op.drop_column("learning_paths", "supersedes_id")
    op.drop_column("learning_paths", "published_at")
    op.drop_column("learning_paths", "sequencing_mode")
    op.drop_column("learning_paths", "version")
    op.drop_column("learning_paths", "family_id")
