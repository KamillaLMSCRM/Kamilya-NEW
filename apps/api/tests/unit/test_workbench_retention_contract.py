"""Database-free migration/interface guards; real retention is the owned DEV gate."""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.methodologist_workbench.assignment_models import AssignmentPlan

ROOT = Path(__file__).resolve().parents[4]


def load_migration():
    path = ROOT / "apps/api/alembic/versions/0171_workbench_plan_retention.py"
    spec = importlib.util.spec_from_file_location("retention_contract_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(monkeypatch, schema="workbench_123456789abc"):
    module = load_migration()
    result = []
    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": schema}))
    monkeypatch.setattr(module.op, "execute", result.append)
    module.upgrade()
    return module, result


def test_additive_execution_column_without_backfill_or_runtime_update_grant(monkeypatch):
    module, ddl = statements(monkeypatch)
    assert module.revision == "0171" and module.down_revision == "0170"
    assert AssignmentPlan.__table__.c.executed_at.nullable
    assert AssignmentPlan.__table__.c.executed_at.server_onupdate is not None
    assert any("ADD COLUMN executed_at timestamptz" in item for item in ddl)
    assert not any("UPDATE " in item and "CREATE FUNCTION" not in item and "CREATE TRIGGER" not in item for item in ddl)
    assert not any("GRANT UPDATE" in item for item in ddl)
    assert not any("DROP " in item or "BYPASSRLS" in item or "DISABLE" in item for item in ddl)


def test_timestamp_and_terminal_receipt_are_database_owned(monkeypatch):
    _, ddl = statements(monkeypatch)
    stamp = next(item for item in ddl if "CREATE FUNCTION" in item and "RETURNS trigger" in item)
    assert "NEW.executed_at := clock_timestamp()" in stamp
    assert "TG_OP='INSERT'" in stamp and "NEW.status <> 'ready'" in stamp
    assert "OLD.status='succeeded'" in stamp
    assert "NEW.receipt IS DISTINCT FROM OLD.receipt" in stamp
    assert "NEW.executed_at IS DISTINCT FROM OLD.executed_at" in stamp
    assert any("BEFORE INSERT OR UPDATE" in item for item in ddl)


def test_cleanup_bounded_invoker_exact_tenant_and_database_clock(monkeypatch):
    _, ddl = statements(monkeypatch)
    cleanup = next(item for item in ddl if "CREATE FUNCTION" in item and "RETURNS TABLE" in item)
    assert "p_limit integer DEFAULT 100,p_apply boolean DEFAULT false" in cleanup
    assert "p_limit < 1 OR p_limit > 500" in cleanup and "p_apply IS NULL" in cleanup
    assert "current_user <> 'lms_app'" in cleanup
    assert "app.is_superadmin" in cleanup and "app.tenant_id" in cleanup
    assert "SECURITY INVOKER SET search_path=pg_catalog" in cleanup
    assert "p.tenant_id=v_tenant" in cleanup
    assert "interval '24 hours'" in cleanup and "interval '90 days'" in cleanup
    assert "p.executed_at IS NOT NULL" in cleanup
    assert "transaction_timestamp()" in cleanup
    assert "LIMIT p_limit FOR UPDATE OF p SKIP LOCKED" in cleanup
    assert "RETURNING p.id,p.status" in cleanup
    assert "SECURITY DEFINER" not in "\n".join(ddl)
    assert "CREATE POLICY" not in "\n".join(ddl) and "GRANT DELETE" not in "\n".join(ddl)
    assert "public." not in "\n".join(ddl)
    assert "enrollments" not in cleanup and "user_invitations" not in cleanup


def test_function_acl_revokes_public_and_non_runtime_roles(monkeypatch):
    _, ddl = statements(monkeypatch)
    combined = "\n".join(ddl)
    for name in ("stamp_workbench_execution_time()", "cleanup_workbench_assignment_plans(integer,boolean)"):
        assert f".{name} FROM PUBLIC,lms_app" in combined
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        assert f"FROM {role}" in combined
    grants = [item for item in ddl if item.startswith("GRANT")]
    assert grants == [
        'GRANT EXECUTE ON FUNCTION "workbench_123456789abc".cleanup_workbench_assignment_plans(integer,boolean) TO lms_app'
    ]


@pytest.mark.parametrize("schema", ["public;DROP", "../public", "A", 'public"', "x" * 64])
def test_unsafe_schema_stops_before_ddl(monkeypatch, schema):
    with pytest.raises(ValueError, match="Unsafe workbench schema"):
        statements(monkeypatch, schema)


def test_downgrade_preserves_execution_evidence():
    with pytest.raises(RuntimeError, match="roll-forward only"):
        load_migration().downgrade()


def test_isolated_gate_wires_populated_upgrade_and_actual_retention_checks():
    source = (ROOT / "scripts/ops/workbench_assignment_dev_gate.py").read_text(encoding="utf-8")
    calls = {
        node.func.id: [arg.id for arg in node.args]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"verify_retention_upgrade", "verify_retention"}
    }
    assert calls["verify_retention_upgrade"] == ["connection", "schema", "migration", "RETENTION_MIGRATION"]
    assert calls["verify_retention"] == ["owner_engine", "runtime_engine", "schema", "actor", "other_tenant", "request"]
    assert "or row.executed_at is not None" in source
