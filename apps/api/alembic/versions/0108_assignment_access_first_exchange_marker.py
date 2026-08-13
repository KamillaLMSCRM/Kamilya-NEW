"""Separate public link expiry from an issued assignment session.

Revision ID: 0108
Revises: 0107
"""

import sqlalchemy as sa

from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignment_access_credentials",
        sa.Column("first_exchanged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (
          SELECT 1 FROM assignment_access_credentials
          WHERE first_exchanged_at IS NOT NULL
        ) THEN
          RAISE EXCEPTION
            '0108 downgrade refused: first-exchange history exists; archive it before downgrade';
        END IF;
        END $$"""
    )
    op.drop_column("assignment_access_credentials", "first_exchanged_at")
