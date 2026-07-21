"""Persist AI course and lesson source provenance.

Revision ID: 0068
Revises: 0067
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "source_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "courses",
        sa.Column("source_strategy", sa.Text(), nullable=False, server_default="single_topic"),
    )
    op.add_column("courses", sa.Column("source_combination_goal", sa.Text(), nullable=True))
    op.add_column(
        "courses",
        sa.Column(
            "source_analysis",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_course_source_strategy",
        "courses",
        "source_strategy IN ('single_topic', 'intentional_combination')",
    )
    op.add_column(
        "lessons",
        sa.Column(
            "source_document_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "source_validation_status",
            sa.Text(),
            nullable=False,
            server_default="not_applicable",
        ),
    )
    op.create_check_constraint(
        "ck_lesson_source_validation_status",
        "lessons",
        "source_validation_status IN ('not_applicable', 'verified', 'needs_review')",
    )
    op.add_column(
        "lessons",
        sa.Column(
            "source_references",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_courses_source_document_ids",
        "courses",
        ["source_document_ids"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_lessons_source_document_ids",
        "lessons",
        ["source_document_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_lessons_source_document_ids", table_name="lessons")
    op.drop_index("ix_courses_source_document_ids", table_name="courses")
    op.drop_column("lessons", "source_references")
    op.drop_constraint("ck_lesson_source_validation_status", "lessons", type_="check")
    op.drop_column("lessons", "source_validation_status")
    op.drop_column("lessons", "source_document_ids")
    op.drop_constraint("ck_course_source_strategy", "courses", type_="check")
    op.drop_column("courses", "source_combination_goal")
    op.drop_column("courses", "source_analysis")
    op.drop_column("courses", "source_strategy")
    op.drop_column("courses", "source_document_ids")
