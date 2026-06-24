"""add document_embeddings table with pgvector

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create document_embeddings table
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_embeddings (
            id TEXT PRIMARY KEY,
            tenant_id UUID NOT NULL,
            doc_id TEXT NOT NULL,
            text TEXT NOT NULL,
            headings TEXT NOT NULL DEFAULT '',
            doc_name TEXT NOT NULL DEFAULT '',
            embedding vector(4096)
        )
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_embeddings_tenant ON document_embeddings (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_embeddings_doc ON document_embeddings (doc_id)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_embeddings_embedding
        ON document_embeddings USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 10)
    """)


def downgrade() -> None:
    op.drop_table("document_embeddings")
