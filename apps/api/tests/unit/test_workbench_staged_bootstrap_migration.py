"""Contract tests for the staged 0169/0172 bootstrap-helper seam."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = "tenants_123456789abc"


def test_alembic_catalog_loads_without_application_import_path(tmp_path):
    script_location = str(ROOT / "apps/api/alembic")
    code = (
        "import sys; from alembic.config import Config; "
        "from alembic.script import ScriptDirectory; c=Config(); "
        f"c.set_main_option('script_location', {script_location!r}); "
        "s=ScriptDirectory.from_config(c); assert len(s.get_heads())==1; "
        "assert s.get_revision('0169').down_revision=='0168'; "
        "assert s.get_revision('0172').down_revision=='0171'; "
        "assert 'app' not in sys.modules; print('CATALOG_PASS')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CATALOG_PASS"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrations(monkeypatch):
    expand = _load("migration_0169_staged_contract", "apps/api/alembic/versions/0169_workbench_assignment_plans.py")
    final = _load("migration_0172_staged_contract", "apps/api/alembic/versions/0172_tenants_scoped_bootstrap_rls.py")
    for module in (expand, final):
        monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": SCHEMA}))
    return expand, final


def _bootstrap_statements(module, monkeypatch):
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.install_bootstrap()
    return statements


def _expand_bootstrap_statements(module, monkeypatch):
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module._install_bootstrap(SCHEMA, module.op.execute)
    return statements


def test_0169_and_0172_emit_identical_bootstrap_helpers(migrations, monkeypatch):
    expand, final = migrations
    assert _expand_bootstrap_statements(expand, monkeypatch) == _bootstrap_statements(final, monkeypatch)


def test_shared_helpers_keep_owner_and_acl_invariants(migrations, monkeypatch):
    _, final = migrations
    joined = "\n".join(_bootstrap_statements(final, monkeypatch))
    assert joined.count("SECURITY DEFINER SET search_path = pg_catalog") == 2
    assert "function_owner IN ('lms_app', 'public')" in joined
    assert "function_owner IS DISTINCT FROM other_owner" in joined
    assert joined.count("FROM PUBLIC") == 2
    assert joined.count("GRANT EXECUTE") == 2


def test_0169_is_expand_only_for_tenants_and_preserves_helpers_on_downgrade(migrations, monkeypatch):
    expand, _ = migrations
    statements: list[str] = []
    monkeypatch.setattr(expand.op, "execute", statements.append)
    expand.upgrade()
    joined = "\n".join(statements)
    assert "CREATE OR REPLACE FUNCTION" in joined
    assert 'ALTER TABLE "tenants_123456789abc".workbench_assignment_plans ENABLE ROW LEVEL SECURITY' in joined
    assert 'ALTER TABLE "tenants_123456789abc".workbench_assignment_plans FORCE ROW LEVEL SECURITY' in joined
    tenant_sql = "\n".join(statement for statement in statements if ".tenants" in statement)
    assert "ALTER TABLE" not in tenant_sql
    assert "service_access" not in tenant_sql
    assert "tenants_own_context" not in tenant_sql

    monkeypatch.setattr(expand.op, "get_bind", lambda: SimpleNamespace(execute=lambda _sql: SimpleNamespace(scalar=lambda: False)))
    statements.clear()
    expand.downgrade()
    assert not any("FUNCTION" in statement or "DROP POLICY" in statement for statement in statements)


@pytest.mark.parametrize("schema", ["public;DROP", 'x"', "../public"])
def test_0169_rejects_unsafe_schema_before_helper_sql(migrations, monkeypatch, schema):
    expand, _ = migrations
    monkeypatch.setattr(expand.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": schema}))
    def execute(_sql):
        pytest.fail("unsafe schema emitted SQL")
    monkeypatch.setattr(expand.op, "execute", execute)
    with pytest.raises(ValueError, match="Unsafe workbench schema"):
        expand.upgrade()
