"""fix_documents_rename_size_to_file_size

Rename documents.size to documents.file_size to match SQLAlchemy model.

Revision ID: 0014_fix_documents_rename
Revises: 0013e_rls_correct
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_fix_documents_rename"
down_revision = "0013e_rls_correct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename documents.size to documents.file_size
    op.alter_column("documents", "size", new_column_name="file_size")
    # Update server default
    op.alter_column(
        "documents",
        "file_size",
        server_default="0",
    )


def downgrade() -> None:
    op.alter_column("documents", "file_size", new_column_name="size")
    op.alter_column(
        "documents",
        "size",
        server_default=None,
    )
