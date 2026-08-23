"""Add tenant-scoped RU/KK-compatible full-text retrieval index.

Revision ID: 0130
Revises: 0129
Create Date: 2026-08-23
"""

from alembic import op


revision = "0130"
down_revision = "0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD COLUMN embedding_fts tsvector
            GENERATED ALWAYS AS (
                setweight(
                    to_tsvector('russian'::regconfig, COALESCE(text, '')),
                    'A'
                ) ||
                setweight(
                    to_tsvector('simple'::regconfig, COALESCE(text, '')),
                    'B'
                )
            ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_embeddings_verified_fts
            ON document_embeddings USING GIN (embedding_fts)
            WHERE embedding_provenance_state = 'verified'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_verified_fts")
    op.execute(
        """
        ALTER TABLE document_embeddings
            DROP COLUMN IF EXISTS embedding_fts
        """
    )
