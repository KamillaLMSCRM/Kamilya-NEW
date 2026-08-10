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
