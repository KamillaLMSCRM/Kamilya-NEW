from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0168_privacy_processing_audit_immutability.py"
)


def test_runtime_audit_ledger_is_append_only_after_upgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("def downgrade", maxsplit=1)[0]

    assert 'revision = "0168"' in source
    assert 'down_revision = "0167"' in source
    assert "REVOKE UPDATE, DELETE ON audit_logs FROM lms_app" in upgrade


def test_downgrade_does_not_restore_runtime_delete_permission() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade", maxsplit=1)[1]

    assert "GRANT UPDATE ON audit_logs TO lms_app" in downgrade
    assert "GRANT DELETE" not in downgrade
