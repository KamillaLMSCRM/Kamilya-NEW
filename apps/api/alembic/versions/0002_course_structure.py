"""Add modules, lessons, content_blocks, quizzes, questions, quiz_choices tables

Revision ID: 0002_course_structure
Revises: 0001_initial
Create Date: 2026-06-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_course_structure"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # courses
    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_courses_tenant_id", "courses", ["tenant_id"])

    # modules
    op.create_table(
        "modules",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("course_id", postgresql.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="cascade"),
    )
    op.create_index("ix_modules_course_id", "modules", ["course_id"])
    op.create_index("ix_modules_tenant_id", "modules", ["tenant_id"])

    # lessons
    op.create_table(
        "lessons",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("module_id", postgresql.UUID(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False, server_default="text"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="cascade"),
    )
    op.create_index("ix_lessons_module_id", "lessons", ["module_id"])
    op.create_index("ix_lessons_tenant_id", "lessons", ["tenant_id"])

    # content_blocks
    op.create_table(
        "content_blocks",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("lesson_id", postgresql.UUID(), nullable=False),
        sa.Column("block_type", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="cascade"),
    )
    op.create_index("ix_content_blocks_lesson_id", "content_blocks", ["lesson_id"])

    # quizzes
    op.create_table(
        "quizzes",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("lesson_id", postgresql.UUID(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("pass_score", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("time_limit", sa.Integer(), nullable=True),
        sa.Column("attempt_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="cascade"),
    )
    op.create_index("ix_quizzes_lesson_id", "quizzes", ["lesson_id"])

    # questions
    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("quiz_id", postgresql.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pool_group", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="cascade"),
    )
    op.create_index("ix_questions_quiz_id", "questions", ["quiz_id"])

    # quiz_choices
    op.create_table(
        "quiz_choices",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("question_id", postgresql.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="cascade"),
    )
    op.create_index("ix_quiz_choices_question_id", "quiz_choices", ["question_id"])

    # enrollments
    op.create_table(
        "enrollments",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("course_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="enrolled"),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="cascade"),
    )
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"])
    op.create_index("ix_enrollments_user_id", "enrollments", ["user_id"])

    # progress
    op.create_table(
        "progress",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("course_id", postgresql.UUID(), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_spent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="cascade"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="cascade"),
    )
    op.create_index("ix_progress_course_id", "progress", ["course_id"])
    op.create_index("ix_progress_user_id", "progress", ["user_id"])


def downgrade() -> None:
    op.drop_table("progress")
    op.drop_table("enrollments")
    op.drop_table("quiz_choices")
    op.drop_table("questions")
    op.drop_table("quizzes")
    op.drop_table("content_blocks")
    op.drop_table("lessons")
    op.drop_table("modules")
    op.drop_table("courses")
