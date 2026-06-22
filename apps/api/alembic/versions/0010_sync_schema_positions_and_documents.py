"""sync schema: add filename/s3_key/description to documents, create positions

Revision ID: 0010
Revises: 0009_add_document_description
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009_add_document_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Documents: add columns our model expects (skip if exist)
    op.add_column("documents", sa.Column("filename", sa.Text, nullable=False, server_default="unknown"))
    op.add_column("documents", sa.Column("s3_key", sa.Text, nullable=False, server_default=""))
    op.add_column("documents", sa.Column("description", sa.Text, nullable=False, server_default=""))

    # Positions table (new)
    op.create_table(
        "positions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("department", sa.Text, nullable=False, server_default=""),
        sa.Column("level", sa.Text, nullable=False, server_default=""),
        sa.Column("responsibilities", sa.Text, nullable=False, server_default=""),
        sa.Column("requirements", sa.Text, nullable=False, server_default=""),
        sa.Column("course_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("employee_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("positions")
    op.drop_column("documents", "description")
    op.drop_column("documents", "s3_key")
    op.drop_column("documents", "filename")
