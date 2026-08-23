"""Add version-scoped chunk ordering for contextual retrieval.

Revision ID: 0129
Revises: 0128
Create Date: 2026-08-23
"""

from alembic import op


revision = "0129"
down_revision = "0128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD COLUMN chunk_index INTEGER
        """
    )
    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD CONSTRAINT ck_document_embeddings_verified_chunk_index
                CHECK (
                    embedding_provenance_state <> 'verified'
                    OR (chunk_index IS NOT NULL AND chunk_index >= 0)
                ) NOT VALID,
            ADD CONSTRAINT ck_document_embeddings_legacy_chunk_index
                CHECK (
                    embedding_provenance_state <> 'legacy_unclassified'
                    OR chunk_index IS NULL
                )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_embeddings_tenant_doc_revision_chunk
            ON document_embeddings (
                tenant_id,
                doc_id,
                embedding_source_revision,
                chunk_index
            )
            WHERE embedding_provenance_state = 'verified'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_document_embeddings_tenant_doc_revision_chunk
        """
    )
    op.execute(
        """
        ALTER TABLE document_embeddings
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_legacy_chunk_index,
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_verified_chunk_index,
            DROP COLUMN IF EXISTS chunk_index
        """
    )
