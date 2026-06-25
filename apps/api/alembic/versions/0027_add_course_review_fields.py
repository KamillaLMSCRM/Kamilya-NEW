"""add course review fields

Adds fields to courses to support методолог (methodologist) approval workflow:
- review_status: 'pending' | 'approved' | 'needs_changes' (default 'pending')
- reviewed_by: nullable FK to users.id (the methodologist who approved/flagged)
- reviewed_at: nullable timestamp (when the review happened)
- review_comment: nullable text (methodologist's note, e.g. why needs_changes)

Multi-tenancy: per-course review fields, scoped by tenant via existing
courses.tenant_id. reviewed_by user is resolved per request (no separate
tenant_id column needed).

Motivation: AI-generated courses (and even manually authored ones) need
an explicit "approved by responsible person" step before being assigned
to employees. Required for compliance with КоАП ст. 410 РК — regulator
needs to know who signed off on training content.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum-style review_status. We use a string + check constraint rather
    # than a Postgres ENUM type so adding new statuses later doesn't need
    # a migration on the type itself.
    op.add_column(
        "courses",
        sa.Column(
            "review_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.create_check_constraint(
        "ck_course_review_status",
        "courses",
        "review_status IN ('pending', 'approved', 'needs_changes')",
    )
    op.add_column(
        "courses",
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_courses_reviewed_by",
        "courses",
        ["reviewed_by"],
    )
    op.add_column(
        "courses",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("review_comment", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "review_comment")
    op.drop_column("courses", "reviewed_at")
    op.drop_index("ix_courses_reviewed_by", table_name="courses")
    op.drop_column("courses", "reviewed_by")
    op.drop_constraint("ck_course_review_status", "courses", type_="check")
    op.drop_column("courses", "review_status")
