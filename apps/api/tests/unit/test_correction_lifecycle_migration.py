"""Database-free static contracts for the 0178 correction lifecycle migration.

These assertions exercise the migration's external Alembic operation seam only;
they do not prove PostgreSQL execution, RLS behavior, locking, or trigger
semantics. Those properties require the owned DEV gate.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
MIGRATION = ROOT / "apps/api/alembic/versions/0178_workbench_lesson_correction_lifecycle.py"


def _load():
    spec = importlib.util.spec_from_file_location("correction_lifecycle_0178_contract", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(monkeypatch, schema="workbench_123456789abc"):
    module = _load()
    statements = []
    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": schema}))
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    return module, statements


def test_revision_and_schema_guard_are_additive_and_bounded(monkeypatch):
    module, statements = _upgrade(monkeypatch)
    assert module.revision == "0178"
    assert module.down_revision == "0177"
    assert any("CREATE TABLE" in statement and "workbench_lesson_correction_accounting" in statement for statement in statements)
    for schema in ["PUBLIC", "public;DROP TABLE users", "../public", "x" * 64]:
        with pytest.raises(ValueError, match="Unsafe correction lifecycle schema"):
            _upgrade(monkeypatch, schema)


def test_accounting_table_and_trigger_preserve_marker_month_and_refund_invariants(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    combined = "\n".join(statements)
    table = next(statement for statement in statements if "CREATE TABLE" in statement)
    trigger = next(statement for statement in statements if "RETURNS trigger" in statement)
    assert "plan_id uuid PRIMARY KEY" in table
    assert "ON DELETE CASCADE" in table
    assert "month_key varchar(7)" in table
    assert "estimated_cost_cents integer NOT NULL CHECK(estimated_cost_cents=10)" in table
    assert "provider_boundary_at" in table and "settled_at" in table
    assert "OR(state='started' AND provider_boundary_at IS NOT NULL" in table
    assert "OR(state IN('charged','retained')" in table
    assert "NEW.month_key<>to_char((p.snapshot->>'created_at')::timestamptz AT TIME ZONE 'UTC','YYYY-MM')" in trigger
    assert "NEW.provider_boundary_at := clock_timestamp()" in trigger
    assert "NEW.provider_boundary_at IS DISTINCT FROM OLD.provider_boundary_at" in trigger
    assert "cost_cents>=OLD.estimated_cost_cents" in trigger
    assert "request_count>=1" in trigger
    assert "RETURNING id INTO refunded_usage" in trigger
    assert "correction_accounting_pending" in trigger
    assert "GREATEST" not in trigger
    assert "SECURITY INVOKER SET search_path=pg_catalog" in combined


def test_rls_acl_and_maintenance_authority_are_explicit(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    combined = "\n".join(statements)
    for phrase in (
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "CREATE POLICY correction_accounting_read",
        "CREATE POLICY correction_accounting_insert",
        "CREATE POLICY correction_accounting_update",
        "CREATE POLICY correction_accounting_purge",
        "CREATE POLICY correction_maintenance_close",
        "CREATE POLICY correction_application_maintenance_read",
        "current_user<>'lms_app'",
        "app.is_superadmin",
        "WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND COALESCE(current_setting('app.is_superadmin',true),'false')='true' AND status='failed')",
    ):
        assert phrase in combined
    for role in ("PUBLIC", "anon", "authenticated", "service_role", "lms_recovery"):
        assert f"FROM {role}" in combined
    assert 'GRANT SELECT,INSERT,DELETE ON "workbench_123456789abc".workbench_lesson_correction_accounting TO lms_app' in combined
    assert 'GRANT UPDATE(state) ON "workbench_123456789abc".workbench_lesson_correction_accounting TO lms_app' in combined
    assert "SECURITY DEFINER" not in combined


def test_maintenance_is_tenant_bounded_deterministic_and_retention_aware(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    maintenance = next(statement for statement in statements if "CREATE FUNCTION" in statement and "RETURNS TABLE(plan_id uuid,action text)" in statement)
    assert "p_limit integer DEFAULT 100,p_apply boolean DEFAULT false" in maintenance
    assert "p_limit<1 OR p_limit>500" in maintenance
    assert "p_apply IS NULL" in maintenance
    assert "FOR UPDATE OF p SKIP LOCKED" in maintenance
    assert "transaction_timestamp()" in maintenance
    assert "interval '24 hours'" in maintenance
    assert "interval '90 days'" in maintenance
    assert "p.tenant_id=v_tenant" in maintenance
    assert "ORDER BY" in maintenance and ",p.id" in maintenance
    assert "RETURN QUERY SELECT p.id AS selected_id" in maintenance
    assert "UPDATE \"workbench_123456789abc\".workbench_lesson_correction_plans SET status='failed',error_code='proposal_interrupted'" in maintenance
    assert "DELETE FROM \"workbench_123456789abc\".workbench_lesson_correction_plans WHERE id=candidate.selected_id AND tenant_id=v_tenant" in maintenance
    assert "state NOT IN('reserved','started')" in maintenance
    assert "CASE WHEN state='reserved' THEN 'refunded' ELSE 'retained' END" in maintenance


def test_exact_tenant_purge_orders_accounting_receipts_before_parent():
    purge = (ROOT / "apps/api/app/modules/admin/superadmin/service.py").read_text(encoding="utf-8")
    ledger = "DELETE FROM workbench_lesson_correction_accounting WHERE tenant_id = :tenant_id"
    receipts = "DELETE FROM workbench_lesson_correction_applications WHERE tenant_id = :tenant_id"
    parent = "DELETE FROM workbench_lesson_correction_plans WHERE tenant_id = :tenant_id"
    assert ledger in purge and receipts in purge and parent in purge
    assert purge.index(ledger) < purge.index(receipts) < purge.index(parent)


def test_apply_action_is_derived_after_fresh_accounting_lock(monkeypatch):
    _, statements = _upgrade(monkeypatch)
    maintenance = next(statement for statement in statements if "RETURNS TABLE(plan_id uuid,action text)" in statement)
    fresh_lock = maintenance.index("SELECT * INTO accounting")
    action = maintenance.index("candidate.selected_action := CASE WHEN FOUND")
    parent_write = maintenance.index("SET status='failed',error_code='proposal_interrupted'")
    assert fresh_lock < action < parent_write
    assert "accounting.state='reserved' THEN 'reconcile_refund' ELSE 'reconcile_retain' END" in maintenance


def test_downgrade_refuses_populated_parent_or_accounting_and_allows_empty(monkeypatch):
    module = _load()

    class Result:
        def __init__(self, populated):
            self.populated = populated

        def scalar(self):
            return self.populated

    class Bind:
        def __init__(self, populated):
            self.populated = populated

        def execute(self, _statement):
            return Result(self.populated)

    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "public"}))
    monkeypatch.setattr(module.op, "get_bind", lambda: Bind(True))
    with pytest.raises(RuntimeError, match="requires empty tables"):
        module.downgrade()

    dropped = []
    monkeypatch.setattr(module.op, "get_bind", lambda: Bind(False))
    monkeypatch.setattr(module.op, "execute", dropped.append)
    module.downgrade()
    assert any("DROP TABLE" in statement and "workbench_lesson_correction_accounting" in statement for statement in dropped)
