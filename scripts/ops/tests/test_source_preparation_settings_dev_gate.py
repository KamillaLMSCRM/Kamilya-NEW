"""Offline tests: no provider, credentials or database access."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / "scripts/ops/source_preparation_settings_dev_gate.py"
MIGRATION = ROOT / "apps/api/alembic/versions/0186_source_preparation_settings.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0186_offline", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execute_flag_fails_closed_before_reading_env():
    result = subprocess.run([sys.executable, str(GATE), "--env-file", "does-not-exist.env"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert '"reason": "execute_required"' in result.stdout


def test_migration_only_adds_constraints_and_has_guarded_downgrade():
    migration = load_migration()
    statements = []
    migration.op = SimpleNamespace(get_context=lambda: SimpleNamespace(opts={"version_table_schema": "runtime_cfg_0123456789ab"}),
                                   execute=statements.append)
    migration.upgrade()
    assert len(statements) == 7
    assert all("ALTER TABLE" in statement for statement in statements)
    assert all(key in statements[1] for key in migration.NUMBERS)
    assert all("trunc(" in statement and "jsonb_typeof" in statement for statement in statements[2:])
    statements.clear()
    migration.downgrade()
    assert "ADD CONSTRAINT ck_runtime_settings_keys" in statements[1]
    assert all(key not in statements[1] for key in migration.NUMBERS)
    assert all("DROP CONSTRAINT ck_source_preparation_number_" in statement for statement in statements[2:])


def test_migration_rejects_unsafe_schema():
    migration = load_migration()
    migration.op = SimpleNamespace(get_context=lambda: SimpleNamespace(opts={"version_table_schema": "public;DROP SCHEMA public"}))
    with pytest.raises(ValueError, match="unsafe_runtime_settings_schema"):
        migration.upgrade()
