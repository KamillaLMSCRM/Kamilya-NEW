"""Static contract tests for contextual chunk migration 0129."""

from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0129_add_embedding_chunk_index.py"
)


def test_chunk_index_migration_is_linear_and_fail_closed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0129"' in source
    assert 'down_revision = "0128"' in source
    assert "ADD COLUMN chunk_index INTEGER" in source
    assert "ck_document_embeddings_verified_chunk_index" in source
    assert "chunk_index IS NOT NULL AND chunk_index >= 0" in source
    assert ") NOT VALID" in source
    assert "ck_document_embeddings_legacy_chunk_index" in source
    assert "OR chunk_index IS NULL" in source


def test_chunk_index_migration_has_tenant_revision_order_index_and_safe_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE INDEX ix_document_embeddings_tenant_doc_revision_chunk" in source
    for column in ("tenant_id", "doc_id", "embedding_source_revision", "chunk_index"):
        assert column in source
    assert "WHERE embedding_provenance_state = 'verified'" in source
    assert "DROP INDEX IF EXISTS ix_document_embeddings_tenant_doc_revision_chunk" in source
    assert "DROP COLUMN IF EXISTS chunk_index" in source
    assert "DROP TABLE" not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source
