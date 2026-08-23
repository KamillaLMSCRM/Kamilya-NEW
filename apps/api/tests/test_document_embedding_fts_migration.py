"""Static contract tests for PostgreSQL full-text migration 0130."""

from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0130_add_document_embedding_fts.py"
)


def test_fts_migration_is_linear_generated_and_ru_kk_compatible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0130"' in source
    assert 'down_revision = "0129"' in source
    assert "ADD COLUMN embedding_fts tsvector" in source
    assert "GENERATED ALWAYS AS" in source
    assert "to_tsvector('russian'::regconfig" in source
    assert "to_tsvector('simple'::regconfig" in source
    assert "COALESCE(text, '')" in source


def test_fts_migration_has_verified_partial_gin_index_and_safe_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "USING GIN (embedding_fts)" in source
    assert "WHERE embedding_provenance_state = 'verified'" in source
    assert "DROP INDEX IF EXISTS ix_document_embeddings_verified_fts" in source
    assert "DROP COLUMN IF EXISTS embedding_fts" in source
    assert "DROP TABLE" not in source
    assert "DISABLE ROW LEVEL SECURITY" not in source
