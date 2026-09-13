"""Static contract tests for migration 0159."""

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0159_ai_generation_omitted_lessons.py"
)


def _source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("migration_0159", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_advances_from_0158():
    module = _module()
    assert module.revision == "0159"
    assert module.down_revision == "0158"


def test_migration_adds_omitted_as_terminal_status_for_all_stages():
    source = _source()
    assert "('pending', 'completed', 'failed', 'omitted')" in source
    assert 'for column in ("content", "review", "assessment")' in source
    assert 'f"ck_ai_generation_checkpoint_{column}_status"' in source
    assert "ck_ai_generation_checkpoint_omission_consistency" in source
    assert "content_payload IS NOT NULL" in source
    assert "review_payload IS NULL" in source
    assert "assessment_payload IS NULL" in source


def test_downgrade_restores_original_status_constraints():
    source = _source()[_source().index("def downgrade"):]
    assert "WHERE content_status = 'omitted'" in source
    assert "content_status = 'pending'" in source
    assert "DROP CONSTRAINT" in source
    assert "('pending', 'completed', 'failed')" in source
