"""add_ai_jobs

Revision ID: 0004
Revises: 0003_add_enrollment_progress_documents
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0004"
down_revision = "0003_add_enrollment_progress_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AI generation jobs
    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("course_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("stage", sa.String, nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("params", JSONB, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("errors", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Generated course content (from AI pipeline)
    op.create_table(
        "generated_content",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", sa.String, nullable=False, index=True),
        sa.Column("course_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("content_type", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("generated_content")
    op.drop_table("ai_jobs")
