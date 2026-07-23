"""Repair mojibake arrows in existing matching quiz questions.

Revision ID: 0071
Revises: 0070
"""

from alembic import op


revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE questions
        SET text = replace(text, 'в†’', '→')
        WHERE text LIKE '%в†’%'
        """
    )


def downgrade() -> None:
    # The repaired Unicode text is intentionally not corrupted again.
    pass
