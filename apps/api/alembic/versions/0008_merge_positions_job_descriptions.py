"""merge_positions_job_descriptions

Revision ID: 0008
Revises: 0007_add_positions_job_descriptions
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add JD fields to positions
    op.add_column("positions", sa.Column("responsibilities", sa.Text, nullable=False, server_default=""))
    op.add_column("positions", sa.Column("requirements", sa.Text, nullable=False, server_default=""))
    op.add_column("positions", sa.Column("course_id", UUID(as_uuid=True), nullable=True))

    # Drop job_descriptions table
    op.drop_table("job_descriptions")


def downgrade() -> None:
    # Recreate job_descriptions
    op.create_table(
        "job_descriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("department", sa.Text, nullable=False, server_default=""),
        sa.Column("position", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("requirements", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("course_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Remove JD fields from positions
    op.drop_column("positions", "course_id")
    op.drop_column("positions", "requirements")
    op.drop_column("positions", "responsibilities")
