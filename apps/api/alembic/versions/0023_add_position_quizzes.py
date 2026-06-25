"""add position_quizzes table

Stores AI-generated onboarding quizzes, one per position. Methodologist
generates the initial draft via /positions/{id}/suggest-onboarding-quiz,
edits questions inline, and saves via /positions/{id}/onboarding-quiz.

Questions are stored as a JSON column for v1 (the methodologist edits
them in the modal before saving). A separate Question/QuizChoice table
pair can be added in v1.1 if we need attempts, scoring history, or
question pooling.

is_active controls whether the quiz is auto-assigned during onboarding.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_quizzes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("position_id", UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False, server_default="Онбординг-тест"),
        sa.Column("pass_score", sa.Integer, nullable=False, server_default="80"),
        sa.Column("time_limit", sa.Integer, nullable=True),  # minutes, NULL = unlimited
        sa.Column("questions", JSON, nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("position_quizzes")
