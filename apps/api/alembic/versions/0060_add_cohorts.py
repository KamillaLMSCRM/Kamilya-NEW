"""Add tenant learning cohorts and links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("cohorts", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"))
    op.create_index("ix_cohorts_tenant_id", "cohorts", ["tenant_id"])
    for table, cols, refs, uq in [("cohort_members", ["cohort_id", "user_id"], [("cohort_id", "cohorts.id"), ("user_id", "users.id")], "uq_cohort_member"), ("cohort_courses", ["cohort_id", "course_id"], [("cohort_id", "cohorts.id"), ("course_id", "courses.id")], "uq_cohort_course")]:
        columns = [sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False)] + [sa.Column(col, postgresql.UUID(as_uuid=True), nullable=False) for col in cols]
        constraints = [sa.ForeignKeyConstraint([col], [ref], ondelete="CASCADE") for col, ref in refs] + [sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.UniqueConstraint("tenant_id", *cols, name=uq)]
        op.create_table(table, *columns, *constraints); op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    for table in ("cohorts", "cohort_members", "cohort_courses"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"); op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"); op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"); op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")


def downgrade() -> None:
    for table in ("cohort_courses", "cohort_members", "cohorts"): op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("cohort_courses"); op.drop_table("cohort_members"); op.drop_index("ix_cohorts_tenant_id", table_name="cohorts"); op.drop_table("cohorts")
