"""Add tenant announcements with delivery status."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("recipients_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('draft', 'sent', 'partial')", name="ck_announcement_status"),
    )
    op.create_index("ix_announcements_tenant_id", "announcements", ["tenant_id"])
    op.create_index("ix_announcements_course_id", "announcements", ["course_id"])
    op.execute("ALTER TABLE announcements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE announcements FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON announcements USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON announcements TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON announcements")
    op.drop_index("ix_announcements_course_id", table_name="announcements")
    op.drop_index("ix_announcements_tenant_id", table_name="announcements")
    op.drop_table("announcements")
