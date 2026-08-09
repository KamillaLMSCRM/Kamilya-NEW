"""Add explicit quiz freshness review state.

Revision ID: 0095
Revises: 0094
"""

from alembic import op

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE quizzes ADD COLUMN review_status text NOT NULL DEFAULT 'approved' "
        "CHECK (review_status IN ('approved', 'needs_review'))"
    )
    op.execute("ALTER TABLE quizzes ADD COLUMN reviewed_by uuid NULL")
    op.execute("ALTER TABLE quizzes ADD COLUMN reviewed_at timestamptz NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE quizzes DROP COLUMN reviewed_at")
    op.execute("ALTER TABLE quizzes DROP COLUMN reviewed_by")
    op.execute("ALTER TABLE quizzes DROP COLUMN review_status")
