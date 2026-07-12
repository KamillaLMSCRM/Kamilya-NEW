"""Add tenant-scoped ordered learning paths."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_paths",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_learning_path_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_learning_paths_tenant_id", "learning_paths", ["tenant_id"])
    op.create_table(
        "learning_path_courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["path_id"], ["learning_paths.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("path_id", "course_id", name="uq_learning_path_course"),
        sa.UniqueConstraint("path_id", "order_index", name="uq_learning_path_order"),
    )
    op.create_index("ix_learning_path_courses_path_id", "learning_path_courses", ["path_id"])
    op.create_index("ix_learning_path_courses_course_id", "learning_path_courses", ["course_id"])

    # The link table has no duplicated tenant_id by design. Its policy resolves
    # the tenant through the parent path, so direct SQL access is isolated too.
    for table in ("learning_paths", "learning_path_courses"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON learning_paths
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE POLICY tenant_isolation ON learning_path_courses
        USING (EXISTS (
            SELECT 1 FROM learning_paths p
            WHERE p.id = path_id
              AND p.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM learning_paths p
            WHERE p.id = path_id
              AND p.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        ))
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON learning_paths TO lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON learning_path_courses TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON learning_path_courses")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON learning_paths")
    op.drop_index("ix_learning_path_courses_course_id", table_name="learning_path_courses")
    op.drop_index("ix_learning_path_courses_path_id", table_name="learning_path_courses")
    op.drop_table("learning_path_courses")
    op.drop_index("ix_learning_paths_tenant_id", table_name="learning_paths")
    op.drop_table("learning_paths")
