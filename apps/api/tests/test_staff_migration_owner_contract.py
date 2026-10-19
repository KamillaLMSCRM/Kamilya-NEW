"""Offline contract; real populated non-BYPASS validation lives in the DEV gate."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MIGRATION = Path(__file__).parents[1] / "alembic/versions/0183_staff_structure_changes.py"


def statements(schema="staff_owner_0123456789ab"):
    spec = importlib.util.spec_from_file_location("staff_owner_migration_contract", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = []
    module.op = SimpleNamespace(
        get_context=lambda: SimpleNamespace(opts={"version_table_schema": schema}),
        execute=lambda sql: output.append(str(sql)),
    )
    module.upgrade()
    return output


def test_validation_uses_locked_owner_visibility_and_preserves_named_refusal():
    sql = "\n".join(statements())
    assert sql.count("LEFT JOIN") == 2
    assert "staff_reference_rls_baseline_mismatch" in sql
    assert "c.relrowsecurity AND c.relforcerowsecurity" in sql
    assert "existing_staff_tenant_reference_mismatch" in sql
    assert "ERRCODE='23514'" in sql


def test_all_participants_locked_before_visibility_change_and_reforced_before_ddl():
    items = statements()
    sql = "\n".join(items)
    schema = '"staff_owner_0123456789ab"'
    lock = sql.index(f'LOCK TABLE {schema}.users,{schema}.positions,{schema}.departments IN ACCESS EXCLUSIVE MODE')
    baseline = sql.index("staff_reference_rls_baseline_mismatch")
    validation = sql.index("IF EXISTS(SELECT 1")
    feature_ddl = sql.index("CREATE TABLE")
    for table in ("users", "positions", "departments"):
        unforce = sql.index(f'ALTER TABLE {schema}.{table} NO FORCE ROW LEVEL SECURITY')
        force = sql.index(f'ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY')
        assert lock < baseline < unforce < validation < force < feature_ddl
    assert "CREATE UNIQUE INDEX" not in sql and "ADD CONSTRAINT" not in sql


def test_validation_is_transactional_bounded_and_never_changes_policies_or_roles():
    sql = "\n".join(statements())
    assert "SET LOCAL lock_timeout='5s'" in sql
    assert "SET LOCAL statement_timeout='60s'" in sql
    assert "CONCURRENTLY" not in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" not in sql
    assert "DROP CONSTRAINT IF EXISTS" not in sql
    for forbidden in ("DISABLE ROW LEVEL SECURITY", "ALTER ROLE", "BYPASSRLS", "SECURITY DEFINER", "DROP POLICY", "ALTER POLICY", "COMMIT", "AUTOCOMMIT"):
        assert forbidden not in sql


def test_public_and_isolated_schema_qualification_share_the_same_contract():
    sql = "\n".join(statements("public"))
    assert 'LEFT JOIN "public".positions' in sql
    assert 'LOCK TABLE "public".users,"public".positions,"public".departments' in sql


@pytest.mark.parametrize("schema", ['public;DROP SCHEMA public', 'Public', 'a"b'])
def test_unsafe_schema_rejected_before_any_ddl(schema):
    with pytest.raises(ValueError, match="unsafe_schema"):
        statements(schema)
