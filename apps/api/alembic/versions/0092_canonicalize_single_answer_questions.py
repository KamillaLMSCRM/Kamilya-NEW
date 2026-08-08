"""Canonicalize single-answer questions as MCQ.

Revision ID: 0092
Revises: 0091
Create Date: 2026-08-08
"""

from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE questions AS question
        SET type = 'MCQ'
        WHERE question.type = 'multiple_choice'
          AND 1 = (
              SELECT count(*)
              FROM quiz_choices AS choice
              WHERE choice.question_id = question.id
                AND choice.is_correct IS TRUE
          )
        """
    )


def downgrade() -> None:
    # The former value did not distinguish genuinely multi-answer questions
    # from mislabeled single-answer questions, so restoring it would corrupt
    # the corrected semantics.
    pass
