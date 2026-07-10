"""Add learner assistant messages.

Revision ID: 0052
Revises: 0051
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_learner_assistant_messages_tenant_id", "learner_assistant_messages", ["tenant_id"])
    op.create_index("ix_learner_assistant_messages_user_id", "learner_assistant_messages", ["user_id"])
    op.create_index("ix_learner_assistant_messages_course_id", "learner_assistant_messages", ["course_id"])
    op.create_index("ix_learner_assistant_messages_lesson_id", "learner_assistant_messages", ["lesson_id"])
    op.create_index(
        "ix_learner_assistant_messages_context",
        "learner_assistant_messages",
        ["tenant_id", "user_id", "course_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_learner_assistant_messages_context", table_name="learner_assistant_messages")
    op.drop_index("ix_learner_assistant_messages_lesson_id", table_name="learner_assistant_messages")
    op.drop_index("ix_learner_assistant_messages_course_id", table_name="learner_assistant_messages")
    op.drop_index("ix_learner_assistant_messages_user_id", table_name="learner_assistant_messages")
    op.drop_index("ix_learner_assistant_messages_tenant_id", table_name="learner_assistant_messages")
    op.drop_table("learner_assistant_messages")
