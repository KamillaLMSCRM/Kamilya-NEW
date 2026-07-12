"""Add tenant-scoped post-course surveys."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("surveys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("questions", postgresql.JSONB(), nullable=False, server_default="[]"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_survey_status"),
    )
    op.create_index("ix_surveys_tenant_id", "surveys", ["tenant_id"]); op.create_index("ix_surveys_course_id", "surveys", ["course_id"])
    op.create_table("survey_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("survey_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("answers", postgresql.JSONB(), nullable=False, server_default="{}"), sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["survey_id"], ["surveys.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.UniqueConstraint("tenant_id", "survey_id", "user_id", name="uq_survey_response_user"),
    )
    op.create_index("ix_survey_responses_tenant_id", "survey_responses", ["tenant_id"])
    for table in ("surveys", "survey_responses"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"); op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")


def downgrade() -> None:
    for table in ("survey_responses", "surveys"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("survey_responses"); op.drop_index("ix_surveys_course_id", table_name="surveys"); op.drop_index("ix_surveys_tenant_id", table_name="surveys"); op.drop_table("surveys")
