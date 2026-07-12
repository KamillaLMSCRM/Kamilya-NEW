"""Add tenant-scoped competency matrix links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("competencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_competencies_tenant_name"),
    )
    op.create_index("ix_competencies_tenant_id", "competencies", ["tenant_id"])
    for table, columns, uniques, unique_name in [
        ("position_competencies", [("position_id", "positions.id"), ("competency_id", "competencies.id")], ("tenant_id", "position_id", "competency_id"), "uq_position_competency"),
        ("competency_courses", [("competency_id", "competencies.id"), ("course_id", "courses.id")], ("tenant_id", "competency_id", "course_id"), "uq_competency_course"),
    ]:
        cols = [sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False)]
        for name, _ in columns: cols.append(sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False))
        if table == "position_competencies": cols.append(sa.Column("required_level", sa.Integer(), nullable=False, server_default="1"))
        fks = [sa.ForeignKeyConstraint([name], [target], ondelete="CASCADE") for name, target in columns]
        fks.append(sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"))
        op.create_table(table, *cols, *fks, sa.UniqueConstraint(*uniques, name=unique_name))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    for table in ("competencies", "position_competencies", "competency_courses"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")


def downgrade() -> None:
    for table in ("competency_courses", "position_competencies", "competencies"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
