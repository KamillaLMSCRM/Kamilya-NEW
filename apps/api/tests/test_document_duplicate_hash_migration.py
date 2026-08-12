"""Static contract tests for active document content-hash uniqueness."""

from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0105_active_document_content_hash_unique.py"


def test_active_document_hash_migration_is_linear_and_fails_closed_for_legacy_duplicates() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0105"' in source
    assert 'down_revision = "0104"' in source
    assert "GROUP BY tenant_id, content_sha256" in source
    assert "HAVING count(*) > 1" in source
    assert "upgrade refused" in source
    assert "CREATE UNIQUE INDEX uq_documents_active_tenant_content_sha256" in source
    assert "WHERE lifecycle_status = 'active' AND content_sha256 IS NOT NULL" in source
    assert "DELETE FROM documents" not in source


def test_active_document_hash_migration_downgrade_only_removes_the_index() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "DROP INDEX IF EXISTS uq_documents_active_tenant_content_sha256" in source
