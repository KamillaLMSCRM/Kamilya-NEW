"""Static contract tests for migration 0133."""

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0133_grant_embedding_reindex_runtime_access.py"
)


def _source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("migration_0133", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(operation: str) -> list[str]:
    module = _module()
    statements: list[str] = []
    module.op.execute = statements.append
    getattr(module, operation)()
    return statements


def test_revision_chain_is_0133_after_0132() -> None:
    module = _module()
    assert module.revision == "0133"
    assert module.down_revision == "0132"


def test_runtime_role_receives_only_required_lifecycle_privileges() -> None:
    statements = _statements("upgrade")
    for table in (
        "embedding_active_revisions",
        "embedding_reindex_runs",
        "embedding_reindex_events",
    ):
        assert f"REVOKE ALL ON TABLE {table} FROM PUBLIC, lms_app" in statements
        assert f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app" in statements
    source = _source()
    assert "GRANT DELETE" not in source
    assert "GRANT TRUNCATE" not in source
    assert "BYPASSRLS" not in source


def test_downgrade_revokes_runtime_access_without_dropping_data() -> None:
    statements = _statements("downgrade")
    assert statements == [
        "REVOKE ALL ON TABLE embedding_active_revisions FROM lms_app",
        "REVOKE ALL ON TABLE embedding_reindex_runs FROM lms_app",
        "REVOKE ALL ON TABLE embedding_reindex_events FROM lms_app",
    ]
    source = _source()
    assert "DROP TABLE" not in source
    assert "DELETE FROM" not in source
    assert "TRUNCATE" not in source
