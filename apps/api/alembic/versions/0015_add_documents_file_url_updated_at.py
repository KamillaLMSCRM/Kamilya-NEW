"""add file_url and updated_at to documents table

Revision ID: 0015_add_documents_file_url_updated_at
Revises: 0013e_rls_correct
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_add_documents_file_url_updated_at"
down_revision = "0013e_rls_correct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add file_url column
    op.add_column("documents", sa.Column("file_url", sa.Text, nullable=True))
    # Add updated_at column with default
    op.add_column("documents", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column("documents", "updated_at")
    op.drop_column("documents", "file_url")
