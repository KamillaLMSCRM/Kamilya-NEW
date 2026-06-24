"""add embedding_status to documents

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-25

Adds `embedding_status` ('pending' | 'success' | 'failed') and
`embedding_error` (text, nullable) to the documents table. This lets the
UI show a clear badge when a document has no embeddings (because
ingestion failed at upload time), instead of letting users hit a
confusing error deep inside the Architect agent.
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "embedding_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("embedding_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_documents_embedding_status",
        "documents",
        ["tenant_id", "embedding_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_embedding_status", table_name="documents")
    op.drop_column("documents", "embedding_error")
    op.drop_column("documents", "embedding_status")
