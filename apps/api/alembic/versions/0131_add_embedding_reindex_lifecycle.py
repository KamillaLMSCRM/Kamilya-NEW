"""Add tenant-scoped embedding reindex lifecycle persistence.

Revision ID: 0131
Revises: 0130
Create Date: 2026-08-23
"""

from alembic import op


revision = "0131"
down_revision = "0130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD COLUMN embedding_index_revision_id TEXT,
            ADD COLUMN embedding_reindex_run_id TEXT,
            ADD CONSTRAINT ck_document_embeddings_reindex_binding
                CHECK (
                    (embedding_index_revision_id IS NULL AND embedding_reindex_run_id IS NULL)
                    OR
                    (embedding_index_revision_id IS NOT NULL AND embedding_reindex_run_id IS NOT NULL)
                ) NOT VALID
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_embeddings_index_revision
            ON document_embeddings (
                tenant_id,
                doc_id,
                embedding_index_revision_id
            )
            WHERE embedding_index_revision_id IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE embedding_active_revisions (
            tenant_id UUID NOT NULL,
            document_id UUID NOT NULL,
            active_revision_id TEXT NOT NULL,
            generation BIGINT NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, document_id),
            CONSTRAINT ck_embedding_active_revision_nonempty
                CHECK (length(btrim(active_revision_id)) > 0),
            CONSTRAINT ck_embedding_active_generation_positive
                CHECK (generation > 0)
        )
        """
    )
    op.execute("ALTER TABLE embedding_active_revisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE embedding_active_revisions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY embedding_active_revisions_tenant_isolation
            ON embedding_active_revisions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        CREATE TABLE embedding_reindex_runs (
            tenant_id UUID NOT NULL,
            document_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            state TEXT NOT NULL,
            generation BIGINT NOT NULL DEFAULT 1,
            active_revision_id TEXT NOT NULL,
            candidate_revision_id TEXT NOT NULL,
            previous_revision_id TEXT,
            candidate_manifest_sha256 TEXT NOT NULL,
            expected_chunk_count INTEGER NOT NULL,
            completed_chunk_count INTEGER NOT NULL DEFAULT 0,
            lifecycle_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, document_id, run_id),
            CONSTRAINT ck_embedding_reindex_state
                CHECK (state IN ('staged', 'running', 'ready', 'active', 'aborted', 'rolled_back', 'cleaned')),
            CONSTRAINT ck_embedding_reindex_run_id_nonempty
                CHECK (length(btrim(run_id)) BETWEEN 1 AND 160),
            CONSTRAINT ck_embedding_reindex_generation_nonnegative
                CHECK (generation >= 0),
            CONSTRAINT ck_embedding_reindex_distinct_candidate
                CHECK (active_revision_id <> candidate_revision_id OR state IN ('active', 'cleaned')),
            CONSTRAINT ck_embedding_reindex_manifest_sha256
                CHECK (candidate_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_embedding_reindex_chunk_counts
                CHECK (
                    expected_chunk_count >= 0
                    AND completed_chunk_count >= 0
                    AND completed_chunk_count <= expected_chunk_count
                    AND (
                        state NOT IN ('ready', 'active')
                        OR completed_chunk_count = expected_chunk_count
                    )
                ),
            CONSTRAINT ck_embedding_reindex_state_bindings
                CHECK (
                    (state IN ('staged', 'running', 'ready', 'aborted')
                        AND active_revision_id <> candidate_revision_id)
                    OR (state = 'active'
                        AND active_revision_id = candidate_revision_id
                        AND previous_revision_id IS NOT NULL)
                    OR (state = 'rolled_back'
                        AND previous_revision_id IS NOT NULL
                        AND active_revision_id = previous_revision_id)
                    OR state = 'cleaned'
                )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_embedding_reindex_open_document
            ON embedding_reindex_runs (tenant_id, document_id)
            WHERE state IN ('staged', 'running', 'ready')
        """
    )
    op.execute("ALTER TABLE embedding_reindex_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE embedding_reindex_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY embedding_reindex_runs_tenant_isolation
            ON embedding_reindex_runs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        ALTER TABLE document_embeddings
            ADD CONSTRAINT fk_document_embeddings_reindex_run
            FOREIGN KEY (tenant_id, doc_id, embedding_reindex_run_id)
            REFERENCES embedding_reindex_runs (tenant_id, document_id, run_id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED
            NOT VALID
        """
    )

    op.execute(
        """
        CREATE TABLE embedding_reindex_events (
            tenant_id UUID NOT NULL,
            document_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_sha256 TEXT NOT NULL,
            generation BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, document_id, run_id, event_id),
            UNIQUE (tenant_id, document_id, run_id, generation),
            CONSTRAINT fk_embedding_reindex_event_run
                FOREIGN KEY (tenant_id, document_id, run_id)
                REFERENCES embedding_reindex_runs (tenant_id, document_id, run_id)
                ON DELETE CASCADE,
            CONSTRAINT ck_embedding_reindex_event_id_nonempty
                CHECK (length(btrim(event_id)) > 0),
            CONSTRAINT ck_embedding_reindex_event_sha256
                CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_embedding_reindex_event_generation_positive
                CHECK (generation > 0)
        )
        """
    )
    op.execute("ALTER TABLE embedding_reindex_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE embedding_reindex_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY embedding_reindex_events_tenant_isolation
            ON embedding_reindex_events
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS embedding_reindex_events_tenant_isolation ON embedding_reindex_events")
    op.execute("DROP TABLE IF EXISTS embedding_reindex_events")
    op.execute(
        """
        ALTER TABLE document_embeddings
            DROP CONSTRAINT IF EXISTS fk_document_embeddings_reindex_run
        """
    )
    op.execute("DROP POLICY IF EXISTS embedding_reindex_runs_tenant_isolation ON embedding_reindex_runs")
    op.execute("DROP INDEX IF EXISTS uq_embedding_reindex_open_document")
    op.execute("DROP TABLE IF EXISTS embedding_reindex_runs")
    op.execute("DROP POLICY IF EXISTS embedding_active_revisions_tenant_isolation ON embedding_active_revisions")
    op.execute("DROP TABLE IF EXISTS embedding_active_revisions")
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_index_revision")
    op.execute(
        """
        ALTER TABLE document_embeddings
            DROP CONSTRAINT IF EXISTS ck_document_embeddings_reindex_binding,
            DROP COLUMN IF EXISTS embedding_reindex_run_id,
            DROP COLUMN IF EXISTS embedding_index_revision_id
        """
    )
