import importlib.util
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0176_workbench_lesson_correction_previews.py"
)


def _text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_is_single_additive_head_with_owned_identity_and_state_guard():
    text = _text()
    assert 'revision = "0176"' in text
    assert 'down_revision = "0175"' in text
    assert text.count("CREATE TABLE") == 1
    assert "workbench_lesson_correction_plans" in text
    assert "UNIQUE (tenant_id,actor_id,request_key)" in text
    assert "snapshot" in text and "request_digest" in text
    assert "status='pending'" in text
    assert "status='ready'" in text
    assert "status='failed'" in text
    assert "Correction context is immutable" in text
    assert "Correction result is immutable" in text


def test_migration_has_force_rls_eligible_ready_and_owned_failed_closure():
    text = _text()
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "CREATE POLICY correction_read" in text
    assert "CREATE POLICY correction_insert" in text
    assert "CREATE POLICY correction_update" in text
    assert "status='failed' OR" in text
    assert "u.is_active IS TRUE" in text
    assert "u.status='active'" in text
    assert "u.role='methodologist'" in text
    assert "SET search_path=pg_catalog" in text
    assert "SECURITY INVOKER" in text
    # Static SQL assertions are source contracts only; they do not prove runtime RLS.


def test_migration_acl_is_runtime_minimal_and_downgrade_is_empty_only():
    text = _text()
    assert "REVOKE ALL ON" in text
    assert "GRANT SELECT,INSERT,DELETE ON" in text
    assert "GRANT UPDATE (status,proposal,fingerprint,error_code)" in text
    assert "DROP TABLE" in text
    assert "requires an empty table" in text
    assert "DROP COLUMN" not in text.upper()
    assert "CREATE TRIGGER lesson_correction_guard" in text
    assert "CREATE FUNCTION" in text


def test_model_registration_and_tenant_purge_are_wired():
    root = MIGRATION.parents[2]
    registry = (root / "app" / "models" / "registry.py").read_text(encoding="utf-8")
    purge = (root / "app" / "modules" / "admin" / "superadmin" / "service.py").read_text(encoding="utf-8")
    assert "correction_models" in registry
    assert "DELETE FROM workbench_lesson_correction_plans WHERE tenant_id = :tenant_id" in purge


def test_migration_schema_guard_rejects_malicious_or_uppercase_schema_without_db(monkeypatch):
    spec = importlib.util.spec_from_file_location("correction_migration_0176", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    for schema in ["PUBLIC", "public;DROP TABLE users", "public schema"]:
        monkeypatch.setattr(
            migration.op,
            "get_context",
            lambda schema=schema: type("Context", (), {"opts": {"version_table_schema": schema}})(),
        )
        with pytest.raises(ValueError, match="Unsafe correction preview schema"):
            migration._schema()


def test_settings_correction_flag_defaults_off():
    from app.core.config import Settings

    assert Settings.model_fields["METHODOLOGIST_LESSON_CORRECTION_ENABLED"].default is False
