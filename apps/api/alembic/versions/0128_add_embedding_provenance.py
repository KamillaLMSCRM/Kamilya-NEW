"""Add provenance metadata and validation to document embeddings.

Revision ID: 0128
Revises: 0127
Create Date: 2026-08-23
"""

from alembic import op


revision = "0128"
down_revision = "0127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD COLUMN embedding_provenance_state TEXT NOT NULL
                DEFAULT 'legacy_unclassified',
            ADD COLUMN embedding_provider TEXT,
            ADD COLUMN embedding_model TEXT,
            ADD COLUMN embedding_revision TEXT,
            ADD COLUMN embedding_native_dimensions INTEGER,
            ADD COLUMN embedding_storage_dimensions INTEGER,
            ADD COLUMN embedding_content_sha256 TEXT,
            ADD COLUMN embedding_source_revision TEXT,
            ADD COLUMN embedding_indexed_at TIMESTAMP WITH TIME ZONE
        """
    )
    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD CONSTRAINT ck_document_embeddings_provenance_state
                CHECK (embedding_provenance_state IN
                    ('legacy_unclassified', 'verified')),
            ADD CONSTRAINT ck_document_embeddings_provenance_dimensions
                CHECK (
                    (embedding_native_dimensions IS NULL
                        OR embedding_native_dimensions > 0)
                    AND (embedding_storage_dimensions IS NULL
                        OR embedding_storage_dimensions > 0)
                    AND (
                        embedding_native_dimensions IS NULL
                        OR embedding_storage_dimensions IS NULL
                        OR embedding_native_dimensions <= embedding_storage_dimensions
                    )
                ),
            ADD CONSTRAINT ck_document_embeddings_content_sha256
                CHECK (
                    embedding_content_sha256 IS NULL
                    OR embedding_content_sha256 ~ '^[0-9a-f]{64}$'
                ),
            ADD CONSTRAINT ck_document_embeddings_legacy_provenance
                CHECK (
                    embedding_provenance_state <> 'legacy_unclassified'
                    OR (
                        embedding_provider IS NULL
                        AND embedding_model IS NULL
                        AND embedding_revision IS NULL
                        AND embedding_native_dimensions IS NULL
                        AND embedding_storage_dimensions IS NULL
                        AND embedding_content_sha256 IS NULL
                        AND embedding_source_revision IS NULL
                        AND embedding_indexed_at IS NULL
                    )
                ),
            ADD CONSTRAINT ck_document_embeddings_verified_provenance
                CHECK (
                    embedding_provenance_state <> 'verified'
                    OR (
                        embedding_provider IS NOT NULL
                        AND btrim(embedding_provider) <> ''
                        AND embedding_model IS NOT NULL
                        AND btrim(embedding_model) <> ''
                        AND embedding_revision IS NOT NULL
                        AND btrim(embedding_revision) <> ''
                        AND embedding_native_dimensions IS NOT NULL
                        AND embedding_native_dimensions > 0
                        AND embedding_storage_dimensions IS NOT NULL
                        AND embedding_storage_dimensions > 0
                        AND embedding_content_sha256 IS NOT NULL
                        AND embedding_content_sha256 ~ '^[0-9a-f]{64}$'
                        AND embedding_source_revision IS NOT NULL
                        AND btrim(embedding_source_revision) <> ''
                        AND embedding_indexed_at IS NOT NULL
                    )
                )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_embeddings_tenant_provenance_revision
            ON document_embeddings (
                tenant_id,
                embedding_provenance_state,
                embedding_revision,
                embedding_source_revision
            )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_document_embeddings_tenant_provenance_revision
        """
    )
    op.execute(
        """
        ALTER TABLE document_embeddings
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_verified_provenance,
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_legacy_provenance,
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_content_sha256,
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_provenance_dimensions,
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_provenance_state
        """
    )
    op.execute(
        """
        ALTER TABLE document_embeddings
            DROP COLUMN IF EXISTS embedding_indexed_at,
            DROP COLUMN IF EXISTS embedding_source_revision,
            DROP COLUMN IF EXISTS embedding_content_sha256,
            DROP COLUMN IF EXISTS embedding_storage_dimensions,
            DROP COLUMN IF EXISTS embedding_native_dimensions,
            DROP COLUMN IF EXISTS embedding_revision,
            DROP COLUMN IF EXISTS embedding_model,
            DROP COLUMN IF EXISTS embedding_provider,
            DROP COLUMN IF EXISTS embedding_provenance_state
        """
    )
