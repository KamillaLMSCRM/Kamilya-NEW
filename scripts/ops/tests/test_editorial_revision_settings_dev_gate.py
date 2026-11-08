import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / 'scripts/ops/editorial_revision_settings_dev_gate.py'
MIGRATION = ROOT / 'apps/api/alembic/versions/0187_editorial_revision_settings.py'


def load_migration():
    spec = importlib.util.spec_from_file_location('migration_0187_offline', MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execute_required_before_reading_credentials():
    result = subprocess.run([sys.executable, str(GATE), '--env-file', 'missing.env'], capture_output=True, text=True)
    assert result.returncode == 2
    assert 'execute_required' in result.stdout


def test_upgrade_and_downgrade_use_frozen_previous_catalog(monkeypatch):
    m = load_migration()
    statements = []
    previous = SimpleNamespace(_schema=lambda: '"runtime_cfg_0123456789ab"',
        _keys=lambda schema, keys: statements.append((schema, tuple(keys))),
        _original_keys=lambda: ('old',), NUMBERS={'existing': (2, 1, 4, True)})
    monkeypatch.setattr(m, '_previous', lambda: previous)
    monkeypatch.setattr(m, 'op', SimpleNamespace(execute=statements.append))
    m.upgrade()
    assert statements[0][1] == ('old', 'existing', 'generation.editorial_max_revisions', 'generation.editorial_rules_per_review',
                                'generation.editorial_luna_max_tokens', 'generation.editorial_deepseek_max_tokens')
    assert all(x in statements[1] for x in ('jsonb_typeof', 'BETWEEN 1 AND 5', 'trunc('))
    assert all(x in statements[2] for x in ('ck_editorial_rule_part_budget', 'BETWEEN 1 AND 128', 'trunc('))
    assert all(x in statements[3] for x in ('ck_editorial_luna_output_budget', 'BETWEEN 8192 AND 32768', 'trunc('))
    assert all(x in statements[4] for x in ('ck_editorial_deepseek_output_budget', 'BETWEEN 16384 AND 65536', 'trunc('))
    statements.clear()
    m.downgrade()
    assert statements[0][1] == ('old', 'existing')
    assert 'DROP CONSTRAINT ck_editorial_revision_budget' in statements[1]
    assert 'DROP CONSTRAINT ck_editorial_luna_output_budget' in statements[3]
    assert 'DROP CONSTRAINT ck_editorial_deepseek_output_budget' in statements[4]


def test_gate_is_anchored_to_frozen_migrations_and_disposable_schema():
    source = GATE.read_text(encoding='utf-8')
    assert '0182_runtime_settings.py' in source and '0186_source_preparation_settings.py' in source
    assert '0187_editorial_revision_settings.py' in source
    assert 'safe_schema(schema)' in source and 'public_snapshot' in source
    assert 'migration_source_changed_during_gate' in source
