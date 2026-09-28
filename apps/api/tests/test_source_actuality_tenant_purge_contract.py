"""Regression contract for deleting tenants with source-actuality history."""

import runpy
from pathlib import Path
from types import SimpleNamespace

API_ROOT = Path(__file__).parents[1]
MIGRATION = API_ROOT / "alembic" / "versions" / "0166_source_actuality_superadmin_purge.py"
SERVICE = API_ROOT / "app" / "modules" / "admin" / "superadmin" / "service.py"


def test_source_actuality_tables_allow_only_exact_superadmin_tenant_delete(monkeypatch) -> None:
    namespace = runpy.run_path(str(MIGRATION))
    emitted: list[str] = []
    monkeypatch.setattr(namespace["op"], "execute", emitted.append)
    monkeypatch.setattr(
        namespace["op"],
        "get_context",
        lambda: SimpleNamespace(opts={"version_table_schema": "purge_contract"}),
    )
    namespace["upgrade"]()
    upgrade = "\n".join(emitted)
    emitted.clear()
    namespace["downgrade"]()
    downgrade = "\n".join(emitted)

    assert namespace["revision"] == "0166"
    assert namespace["down_revision"] == "0165"
    for table in ("document_change_reviews", "document_source_policies"):
        qualified = f'"purge_contract".{table}'
        assert f"DROP POLICY {table}_tenant ON {qualified}" in upgrade
        assert f"CREATE POLICY {table}_tenant_select ON {qualified}" in upgrade
        assert "FOR SELECT TO lms_app" in upgrade
        assert f"CREATE POLICY {table}_tenant_insert ON {qualified}" in upgrade
        assert "FOR INSERT TO lms_app" in upgrade
        assert f"CREATE POLICY {table}_tenant_update ON {qualified}" in upgrade
        assert "FOR UPDATE TO lms_app" in upgrade
        assert f"GRANT DELETE ON {qualified} TO lms_app" in upgrade
        assert f"ON {qualified}" in upgrade
        assert "FOR DELETE TO lms_app" in upgrade
        assert "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid" in upgrade
        assert "COALESCE(current_setting('app.is_superadmin', true), '') = 'true'" in upgrade
        assert f"REVOKE DELETE ON {qualified} FROM lms_app" in downgrade
        assert f"CREATE POLICY {table}_tenant ON {qualified}" in downgrade


def test_tenant_purge_removes_source_actuality_before_documents_and_users() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    review = source.index('"DELETE FROM document_change_reviews WHERE tenant_id = :tenant_id"')
    policy = source.index('"DELETE FROM document_source_policies WHERE tenant_id = :tenant_id"')
    documents = source.index('"DELETE FROM documents WHERE tenant_id = :tenant_id"')
    users = source.index('"DELETE FROM users WHERE tenant_id = :tenant_id"')
    assert review < policy < documents < users
