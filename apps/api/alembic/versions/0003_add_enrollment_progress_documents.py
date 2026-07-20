"""add_enrollment_progress_documents

Revision ID: 0003
Revises: 0002_course_structure
Create Date: 2026-06-21
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0003"
down_revision = "0002_course_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0002 already creates enrollments and progress. Older environments were
    # bootstrapped from a schema where this migration also created them, so keep
    # the migration compatible with both histories without recreating tables.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "enrollments" not in tables:
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
    else:
        enrollment_indexes = {index["name"] for index in inspector.get_indexes("enrollments")}
        if "ix_enrollments_tenant_id" not in enrollment_indexes:
            op.create_index("ix_enrollments_tenant_id", "enrollments", ["tenant_id"])

    if "progress" not in tables:
        op.create_table(
            "progress",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("lesson_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("completed", sa.Boolean, default=False),
            sa.Column("completion_percent", sa.Integer, nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        progress_columns = {column["name"] for column in inspector.get_columns("progress")}
        if "completion_percent" not in progress_columns:
            op.add_column(
                "progress",
                sa.Column("completion_percent", sa.Integer(), nullable=False, server_default="0"),
            )
        progress_indexes = {index["name"] for index in inspector.get_indexes("progress")}
        if "ix_progress_lesson_id" not in progress_indexes:
            op.create_index("ix_progress_lesson_id", "progress", ["lesson_id"])
        if "ix_progress_tenant_id" not in progress_indexes:
            op.create_index("ix_progress_tenant_id", "progress", ["tenant_id"])

    # documents
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("content_type", sa.String, nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("s3_key", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("documents")
    # enrollments and progress belong to 0002 and must survive this downgrade.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "progress" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("progress")}
        if "completion_percent" in columns:
            op.drop_column("progress", "completion_percent")
        indexes = {index["name"] for index in inspector.get_indexes("progress")}
        if "ix_progress_lesson_id" in indexes:
            op.drop_index("ix_progress_lesson_id", table_name="progress")
        if "ix_progress_tenant_id" in indexes:
            op.drop_index("ix_progress_tenant_id", table_name="progress")
    if "enrollments" in inspector.get_table_names():
        indexes = {index["name"] for index in inspector.get_indexes("enrollments")}
        if "ix_enrollments_tenant_id" in indexes:
            op.drop_index("ix_enrollments_tenant_id", table_name="enrollments")
