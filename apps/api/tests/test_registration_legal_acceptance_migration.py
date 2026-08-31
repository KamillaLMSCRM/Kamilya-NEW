from __future__ import annotations

from pathlib import Path


def test_registration_legal_acceptance_migration_enforces_ownership_and_safe_rollback() -> None:
    migration = Path("alembic/versions/0104_registration_legal_acceptances.py").read_text(encoding="utf-8")

    assert "validate_registration_legal_acceptance_ownership" in migration
    assert "id=NEW.user_id AND tenant_id=NEW.tenant_id" in migration
    assert "trg_validate_registration_legal_acceptance_ownership" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert 'ondelete="RESTRICT"' in migration
    assert "0104 downgrade refused: immutable registration legal acceptance evidence exists" in migration


def test_superadmin_purge_migration_is_exact_tenant_and_delete_only() -> None:
    migration = Path(
        "alembic/versions/0140_superadmin_trial_legal_acceptance_purge.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0140"' in migration
    assert 'down_revision = "0139"' in migration
    assert "GRANT DELETE ON registration_legal_acceptances TO lms_app" in migration
    assert "FOR DELETE TO lms_app" in migration
    assert "current_setting('app.tenant_id', true)" in migration
    assert "current_setting('app.is_superadmin', true)" in migration
    assert "GRANT SELECT" not in migration
    assert "GRANT INSERT" not in migration
    assert "GRANT UPDATE" not in migration
