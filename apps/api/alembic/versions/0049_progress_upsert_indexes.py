"""Add progress upsert indexes.

Revision ID: 0049
Revises: 0048
Create Date: 2026-07-08
"""

from alembic import op


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY tenant_id, user_id, lesson_id
                    ORDER BY
                        completed DESC,
                        completed_at DESC NULLS LAST,
                        last_at DESC NULLS LAST,
                        id
                ) AS rn
            FROM progress
        )
        DELETE FROM progress p
        USING ranked r
        WHERE p.id = r.id AND r.rn > 1
        """
    )

    op.create_index(
        "uq_progress_tenant_user_lesson",
        "progress",
        ["tenant_id", "user_id", "lesson_id"],
        unique=True,
    )
    op.create_index(
        "ix_progress_tenant_user_course_completed",
        "progress",
        ["tenant_id", "user_id", "course_id", "completed"],
    )


def downgrade() -> None:
    op.drop_index("ix_progress_tenant_user_course_completed", table_name="progress")
    op.drop_index("uq_progress_tenant_user_lesson", table_name="progress")
