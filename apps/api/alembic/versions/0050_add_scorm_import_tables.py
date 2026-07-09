"""Add SCORM import tables.

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("delivery_type", sa.Text(), nullable=False, server_default="native"),
    )
    op.create_check_constraint(
        "ck_course_delivery_type",
        "courses",
        "delivery_type IN ('native', 'scorm')",
    )
    op.create_table(
        "scorm_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Text(), nullable=False, server_default="scorm_1_2"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("entrypoint", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_scorm_packages_tenant_id", "scorm_packages", ["tenant_id"])
    op.create_index("ix_scorm_packages_course_id", "scorm_packages", ["course_id"])
    op.create_index("ix_scorm_packages_uploaded_by", "scorm_packages", ["uploaded_by"])
    op.create_table(
        "scorm_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_status", sa.Text(), nullable=True),
        sa.Column("success_status", sa.Text(), nullable=True),
        sa.Column("completion_status", sa.Text(), nullable=True),
        sa.Column("score_raw", sa.Text(), nullable=True),
        sa.Column("lesson_location", sa.Text(), nullable=True),
        sa.Column("total_time", sa.Text(), nullable=True),
        sa.Column("suspend_data", sa.Text(), nullable=True),
        sa.Column("cmi_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_commit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_id"], ["scorm_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_scorm_attempts_tenant_id", "scorm_attempts", ["tenant_id"])
    op.create_index("ix_scorm_attempts_course_id", "scorm_attempts", ["course_id"])
    op.create_index("ix_scorm_attempts_package_id", "scorm_attempts", ["package_id"])
    op.create_index("ix_scorm_attempts_user_id", "scorm_attempts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_scorm_attempts_user_id", table_name="scorm_attempts")
    op.drop_index("ix_scorm_attempts_package_id", table_name="scorm_attempts")
    op.drop_index("ix_scorm_attempts_course_id", table_name="scorm_attempts")
    op.drop_index("ix_scorm_attempts_tenant_id", table_name="scorm_attempts")
    op.drop_table("scorm_attempts")
    op.drop_index("ix_scorm_packages_uploaded_by", table_name="scorm_packages")
    op.drop_index("ix_scorm_packages_course_id", table_name="scorm_packages")
    op.drop_index("ix_scorm_packages_tenant_id", table_name="scorm_packages")
    op.drop_table("scorm_packages")
    op.drop_constraint("ck_course_delivery_type", "courses", type_="check")
    op.drop_column("courses", "delivery_type")
