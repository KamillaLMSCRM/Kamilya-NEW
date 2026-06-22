"""add_document_description

Revision ID: 0009
Revises: 0008_merge_positions_job_descriptions
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008_merge_positions_job_descriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("description", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("documents", "description")
