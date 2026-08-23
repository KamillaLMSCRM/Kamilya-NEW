"""Static contract tests for embedding provenance migration 0128."""

from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0128_add_embedding_provenance.py"
)


def test_embedding_provenance_migration_is_linear_and_validates_verified_rows() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0128"' in source
    assert 'down_revision = "0127"' in source
    assert "embedding_provenance_state TEXT NOT NULL" in source
    assert "DEFAULT 'legacy_unclassified'" in source
    for column in (
        "embedding_provider",
        "embedding_model",
        "embedding_revision",
        "embedding_native_dimensions",
        "embedding_storage_dimensions",
        "embedding_content_sha256",
        "embedding_source_revision",
        "embedding_indexed_at",
    ):
        assert f"ADD COLUMN {column}" in source
        assert f"{column} IS NULL" in source
    assert "'legacy_unclassified'" in source
    assert "'verified'" in source
    assert "embedding_native_dimensions > 0" in source
    assert "embedding_storage_dimensions > 0" in source
    assert "embedding_native_dimensions <= embedding_storage_dimensions" in source
    assert "^[0-9a-f]{64}$" in source
    assert "ck_document_embeddings_legacy_provenance" in source
    assert "embedding_provenance_state <> 'legacy_unclassified'" in source
    assert "embedding_content_sha256 IS NULL" in source
    assert "ck_document_embeddings_verified_provenance" in source
    assert "embedding_indexed_at IS NOT NULL" in source


def test_embedding_provenance_migration_has_tenant_scoped_lookup_and_safe_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE INDEX ix_document_embeddings_tenant_provenance_revision" in source
    )
    assert "tenant_id" in source
    assert "embedding_provenance_state" in source
    assert "embedding_revision" in source
    assert "embedding_source_revision" in source
    assert "DROP INDEX IF EXISTS ix_document_embeddings_tenant_provenance_revision" in source
    assert "DROP TABLE" not in source
    assert "DROP EXTENSION" not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source
    assert "UPDATE document_embeddings" not in source
    assert "embedding vector" not in source
    for constraint in (
        "ck_document_embeddings_verified_provenance",
        "ck_document_embeddings_legacy_provenance",
        "ck_document_embeddings_content_sha256",
        "ck_document_embeddings_provenance_dimensions",
        "ck_document_embeddings_provenance_state",
    ):
        assert f"DROP CONSTRAINT IF EXISTS {constraint}" in source
