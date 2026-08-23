"""Static contract tests for migration 0131."""

import importlib.util
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0131_add_embedding_reindex_lifecycle.py"
)


def _source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("migration_0131", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_0131_after_0130() -> None:
    module = _module()
    assert module.revision == "0131"
    assert module.down_revision == "0130"


def test_migration_adds_fail_closed_embedding_bindings() -> None:
    source = _source()
    assert "embedding_index_revision_id" in source
    assert "embedding_reindex_run_id" in source
    assert "ck_document_embeddings_reindex_binding" in source
    assert "NOT VALID" in source
    assert "ix_document_embeddings_index_revision" in source


def test_migration_adds_active_revision_and_reindex_state_tables() -> None:
    source = _source()
    assert "CREATE TABLE embedding_active_revisions" in source
    assert "CREATE TABLE embedding_reindex_runs" in source
    assert "CREATE TABLE embedding_reindex_events" in source
    assert "uq_embedding_reindex_open_document" in source
    assert "candidate_manifest_sha256" in source
    assert "expected_chunk_count" in source
    assert "completed_chunk_count" in source
    assert "lifecycle_payload JSONB" in source
    assert "state NOT IN ('ready', 'active')" in source
    assert "ck_embedding_reindex_generation_nonnegative" in source
    assert "CHECK (generation >= 0)" in source
    assert "active_revision_id = candidate_revision_id" in source
    assert "active_revision_id = previous_revision_id" in source
    assert "fk_document_embeddings_reindex_run" in source
    assert "DEFERRABLE INITIALLY DEFERRED" in source
    assert "UNIQUE (tenant_id, document_id, run_id, generation)" in source


def test_all_new_tables_force_tenant_rls() -> None:
    source = _source()
    for table in (
        "embedding_active_revisions",
        "embedding_reindex_runs",
        "embedding_reindex_events",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in source
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in source
        assert f"ON {table}" in source
    assert source.count("app.tenant_id") >= 6


def test_downgrade_removes_only_0131_objects() -> None:
    source = _source()
    assert "DROP TABLE IF EXISTS embedding_reindex_events" in source
    assert "DROP TABLE IF EXISTS embedding_reindex_runs" in source
    assert "DROP TABLE IF EXISTS embedding_active_revisions" in source
    assert "DROP COLUMN IF EXISTS embedding_reindex_run_id" in source
    assert "DROP COLUMN IF EXISTS embedding_index_revision_id" in source


def test_migration_does_not_hard_code_public_schema() -> None:
    assert "public." not in _source()
