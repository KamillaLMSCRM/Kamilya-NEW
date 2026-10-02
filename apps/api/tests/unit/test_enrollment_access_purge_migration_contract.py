"""Database-free contract tests for the bounded enrollment-access purge migration."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
MIGRATION_PATH = ROOT / "apps/api/alembic/versions/0173_bounded_enrollment_access_purge.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("bounded_enrollment_access_purge_contract", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _compact(value: str) -> str:
    return " ".join(value.split())


def _upgrade(monkeypatch, schema="tenant_test"):
    module = load_migration()
    statements: list[str] = []
    monkeypatch.setattr(
        module.op,
        "get_context",
        lambda: SimpleNamespace(opts={"version_table_schema": schema}),
    )
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    return module, statements


@pytest.mark.parametrize(
    "schema",
    ["public;DROP", "../public", "A", 'public"', "x" * 64, "-tenant"],
)
def test_unsafe_schema_fails_before_any_sql(monkeypatch, schema):
    module = load_migration()
    statements: list[str] = []
    monkeypatch.setattr(
        module.op,
        "get_context",
        lambda: SimpleNamespace(opts={"version_table_schema": schema}),
    )
    monkeypatch.setattr(module.op, "execute", statements.append)

    with pytest.raises(ValueError, match="Unsafe enrollment purge schema"):
        module.upgrade()

    assert statements == []


def test_function_has_definer_owner_and_fail_closed_runtime_guards(monkeypatch):
    module, statements = _upgrade(monkeypatch)
    assert module.revision == "0173"
    assert module.down_revision == "0172"

    function = _compact(next(item for item in statements if "CREATE FUNCTION" in item))
    assert 'CREATE FUNCTION "tenant_test".superadmin_purge_tenant_enrollment_access' in function
    assert "RETURNS integer LANGUAGE plpgsql SECURITY DEFINER" in function
    assert "SET search_path=pg_catalog,public,pg_temp" in function
    for guard in (
        "session_user <> 'lms_app'",
        "session_user <> 'lms_app' AND session_user <> v_owner",
        "current_user <> v_owner",
        "current_setting('app.is_superadmin',true)",
        "p_tenant_id IS NULL",
        "current_setting('app.tenant_id',true)",
        "p_confirm_slug IS NULL",
    ):
        assert guard in function
    assert "ERRCODE='42501'" in function

    owner = _compact(next(item for item in statements if "ALTER FUNCTION" in item))
    assert "ALTER FUNCTION \"tenant_test\".superadmin_purge_tenant_enrollment_access(uuid,text) OWNER TO" in owner


def test_function_locks_target_and_rejects_protected_or_mismatched_tenants(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    function = _compact(next(item for item in statements if "CREATE FUNCTION" in item))
    assert 'FROM "tenant_test".tenants t WHERE t.id=p_tenant_id FOR UPDATE' in function
    assert "v_slug IS NULL OR v_slug='kamilya' OR v_slug IS DISTINCT FROM p_confirm_slug" in function
    assert "enrollment_access_purge_target_rejected" in function


def test_function_locks_outbox_rows_and_rejects_claimed_work(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    function = _compact(next(item for item in statements if "CREATE FUNCTION" in item))
    assert (
        'FROM "tenant_test".course_assignment_notification_outbox '
        "WHERE tenant_id=p_tenant_id FOR UPDATE"
    ) in function
    assert (
        "WHERE tenant_id=p_tenant_id AND status='claimed'"
        in function
    )
    assert "enrollment_access_purge_notification_claimed" in function
    assert "ERRCODE='55000'" in function


def test_function_deletes_exactly_the_three_bounded_child_tables(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    function = _compact(next(item for item in statements if "CREATE FUNCTION" in item))
    deletes = [line for line in function.split("DELETE FROM ")[1:]]
    assert len(deletes) == 3
    assert deletes[0].startswith('"tenant_test".assignment_access_credentials WHERE tenant_id=p_tenant_id;')
    assert deletes[1].startswith('"tenant_test".enrollment_access_policies WHERE tenant_id=p_tenant_id;')
    assert deletes[2].startswith(
        '"tenant_test".course_assignment_notification_outbox WHERE tenant_id=p_tenant_id;'
    )
    assert "DELETE FROM \"tenant_test\".enrollments" not in function
    assert "DELETE FROM \"tenant_test\".content_releases" not in function


def test_upgrade_acl_grants_only_execute_to_lms_app_and_does_not_weaken_rls(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    combined = "\n".join(statements)
    function_signature = (
        '"tenant_test".superadmin_purge_tenant_enrollment_access(uuid,text)'
    )
    assert f"REVOKE ALL ON FUNCTION {function_signature} FROM PUBLIC,lms_app" in combined
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        assert f"REVOKE ALL ON FUNCTION {function_signature} FROM {role}" in combined
    grants = [item for item in statements if _compact(item).startswith("GRANT ")]
    assert grants == [f"GRANT EXECUTE ON FUNCTION {function_signature} TO lms_app"]
    assert "GRANT DELETE" not in combined
    assert "GRANT ALL ON TABLE" not in combined
    assert "ENABLE ROW LEVEL SECURITY" not in combined
    assert "DISABLE ROW LEVEL SECURITY" not in combined
    assert "BYPASSRLS" not in combined


def test_downgrade_drops_only_the_exact_helper(monkeypatch):
    module = load_migration()
    statements: list[str] = []
    monkeypatch.setattr(
        module.op,
        "get_context",
        lambda: SimpleNamespace(opts={"version_table_schema": "tenant_test"}),
    )
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.downgrade()

    assert statements == [
        'DROP FUNCTION "tenant_test".superadmin_purge_tenant_enrollment_access(uuid,text)'
    ]
