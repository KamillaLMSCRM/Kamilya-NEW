"""add completed_at to progress

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("progress", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("progress", "completed_at")
