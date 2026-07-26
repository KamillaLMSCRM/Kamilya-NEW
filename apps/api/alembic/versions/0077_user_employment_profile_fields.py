"""Persist employee phone and hire date from staff imports.

Revision ID: 0077
Revises: 0076
"""

import sqlalchemy as sa
from alembic import op


revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("hire_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "hire_date")
    op.drop_column("users", "phone")
