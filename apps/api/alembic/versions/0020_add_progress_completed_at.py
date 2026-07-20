"""add completed_at to progress

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-24
"""
import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("progress")}
    if "completed_at" not in columns:
        op.add_column("progress", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("progress")}
    if "completed_at" in columns:
        op.drop_column("progress", "completed_at")
