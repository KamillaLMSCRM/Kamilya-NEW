"""Lock visibility must not authorize real writes by the definer owner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[4] / "apps/api/alembic/versions/0174_tenant_purge_owner_lock.py"


def load():
    spec = importlib.util.spec_from_file_location("tenant_purge_owner_lock", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_owner_lock_policy_requires_bounded_context_and_blocks_actual_updates():
    module = load()
    sql = " ".join(module.lock_policy_sql("owned_test", "kamilya_migrator").split())
    assert 'ON "owned_test".tenants FOR UPDATE TO "kamilya_migrator"' in sql
    for guard in (
        "current_user = 'kamilya_migrator'",
        "session_user = 'lms_app'",
        "session_user = pg_catalog.pg_get_userbyid",
        "current_setting('app.is_superadmin', true) = 'true'",
        "id::text = NULLIF(current_setting('app.tenant_id', true), '')",
        "slug <> 'kamilya'",
        "WITH CHECK (false)",
    ):
        assert guard in sql
    assert "FOR ALL" not in sql and "TO PUBLIC" not in sql
    assert "GRANT" not in sql and "BYPASSRLS" not in sql


@pytest.mark.parametrize("schema,owner", [("public;DROP", "postgres"), ("public", "bad'role"), ("A", "postgres"), ("public", "x" * 64)])
def test_unsafe_identifiers_fail_before_sql(schema, owner):
    with pytest.raises(ValueError):
        load().lock_policy_sql(schema, owner)


def test_upgrade_discovers_actual_database_owner_without_changing_grants(monkeypatch):
    module = load()
    statements = []
    queries = []
    def scalar(query):
        queries.append(str(query))
        return "kamilya_migrator"
    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "owned_test"}))
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=scalar))
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    assert (module.revision, module.down_revision) == ("0174", "0173")
    assert len(queries) == 1 and "pg_database" in queries[0] and "current_database()" in queries[0]
    assert statements == [module.lock_policy_sql("owned_test", "kamilya_migrator")]


def test_downgrade_drops_only_the_owner_lock_policy(monkeypatch):
    module = load()
    statements = []
    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "owned_test"}))
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.downgrade()
    assert statements == ['DROP POLICY tenants_purge_function_owner_lock ON "owned_test".tenants']
