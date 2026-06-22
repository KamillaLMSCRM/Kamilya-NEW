"""add_positions_job_descriptions

Revision ID: 0007
Revises: 0006_add_audit_logs
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006_add_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("department", sa.Text, nullable=False, server_default=""),
        sa.Column("level", sa.Text, nullable=False, server_default=""),
        sa.Column("employee_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

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


def downgrade() -> None:
    op.drop_table("job_descriptions")
    op.drop_table("positions")
