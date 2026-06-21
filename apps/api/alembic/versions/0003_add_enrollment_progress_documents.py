"""add_enrollment_progress_documents

Revision ID: 0003
Revises: 0002_course_structure
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0003"
down_revision = "0002_course_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # enrollment
    op.create_table(
        "enrollments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("status", sa.String, nullable=False, server_default="enrolled"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # progress
    op.create_table(
        "progress",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("lesson_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("completed", sa.Boolean, default=False),
        sa.Column("completion_percent", sa.Integer, default=0),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # documents
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("content_type", sa.String, nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("s3_key", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("progress")
    op.drop_table("enrollments")
