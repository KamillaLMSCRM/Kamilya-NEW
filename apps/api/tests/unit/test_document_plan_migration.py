"""Static guards supplement, never replace, isolated DEV RLS execution."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.modules.admin.superadmin.service import TENANT_DELETE_SQL
from app.modules.methodologist_workbench.document_models import DocumentPlan


def test_document_plan_migration_is_additive_and_owner_bound(monkeypatch):
    path = Path(__file__).resolve().parents[4] / "apps/api/alembic/versions/0175_workbench_document_plans.py"
    spec = importlib.util.spec_from_file_location("document_plan_migration_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "workbench_123456789abc"}))
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    ddl = "\n".join(statements)
    assert module.revision == "0175" and module.down_revision == "0174"
    assert "FORCE ROW LEVEL SECURITY" in ddl and "app.user_id" in ddl and "app.tenant_id" in ddl
    assert "GRANT UPDATE (status,job_id)" in ddl
    assert "NEW.admitted_at := clock_timestamp()" in ddl
    assert "OLD.status='submitted'" in ddl and "NEW.snapshot IS DISTINCT FROM OLD.snapshot" in ddl
    assert "j.user_id=NEW.actor_id" in ddl and "j.tenant_id=NEW.tenant_id" in ddl
    assert "SECURITY INVOKER SET search_path=pg_catalog" in ddl
    assert "SECURITY DEFINER" not in ddl and "public." not in ddl and "BYPASSRLS" not in ddl
    assert DocumentPlan.__table__.c.admitted_at.server_onupdate is not None
    assert TENANT_DELETE_SQL.index("DELETE FROM workbench_document_plans WHERE tenant_id = :tenant_id") < TENANT_DELETE_SQL.index("DELETE FROM ai_jobs WHERE tenant_id = :tenant_id")
