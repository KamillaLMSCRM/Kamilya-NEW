"""Database-free safety contract for the isolated tenant-owner lock gate."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GATE = ROOT / "scripts/ops/tenant_purge_lock_dev_gate.py"


def source() -> str:
    return GATE.read_text(encoding="utf-8")


def test_gate_isolated_schema_and_migration_factory_contract() -> None:
    text = source()
    required = (
        'SCHEMA_RE = re.compile(r"^tenant_lock_[0-9a-f]{12}$")',
        'owner_role = "tenant_lock_owner_" + schema.removeprefix("tenant_lock_")',
        'MIGRATION = ROOT / "apps/api/alembic/versions/0174_tenant_purge_owner_lock.py"',
        "lock_policy_sql",
        "revision, module.down_revision) != (\"0174\", \"0173\")",
        "CREATE SCHEMA {qualified}",
        'GRANT USAGE, CREATE ON SCHEMA {qualified} TO "{owner_role}"',
        'SET LOCAL ROLE "{owner_role}"',
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "await connection.rollback()",
        "temporary_role_absent",
        'run_migration_action(connection, module, schema, "downgrade")',
        "fixture_owner_rls_or_runtime_write_grant_drift",
        "downgrade_lock_policy_not_removed",
        "reapplied_lock_policy_failed",
        "empty_context_lock_rejected",
        "direct_insert_delete_denied",
        "rows_unchanged",
        "public_before == await public_snapshot(connection)",
        'text("RESET ROLE")',
    )
    assert all(item in text for item in required)
    assert text.index("INSERT INTO {qualified}.tenants") < text.index("ALTER TABLE {qualified}.tenants ENABLE")
    assert 'CREATE ROLE "{owner_role}" NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT' in text
    assert "CREATE USER" not in text
    assert "GRANT SUPERUSER" not in text


def test_gate_canonical_identity_guards_and_no_public_business_dml() -> None:
    text = source()
    for item in (
        "canonical_dev_project_required",
        "canonical_dev_identity_mismatch",
        "wrong_migration_owner_identity",
        "wrong_runtime_identity",
        "wrong_database",
        "lms_app_not_non_bypass_runtime_role",
        "migration_session_not_database_owner",
        "owner_role_missing_or_bypass",
        "public_business_mutations",
        "public_revision_catalog_unchanged",
    ):
        assert item in text
    assert "public." not in text.lower()
    assert "DROP SCHEMA" not in text
    assert "DROP TABLE" not in text


def test_gate_checks_red_lock_context_and_update_denial() -> None:
    text = source()
    for item in (
        "ordinary_foreign_protected_missing_lock_rejected",
        "exact_owner_lock_failed",
        "owner_update_rejected",
        "expect_sqlstate_rejection",
        '"42501"',
        "checks.append(\"downgrade_policy_removed\")",
        "checks.append(\"lock_policy_reapplied\")",
    ):
        # The policy predicate is migration-owned; the gate must still prove
        # the corresponding observable outcomes and lifecycle transitions.
        assert item in text


def test_gate_parses_without_top_level_network_or_process_calls() -> None:
    tree = ast.parse(source())
    forbidden = {"subprocess", "requests", "httpx", "socket", "os.system"}
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert not names.intersection(forbidden)
