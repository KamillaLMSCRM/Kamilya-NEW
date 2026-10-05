"""Static receipt SQL contracts; not runtime RLS/transaction/FK evidence."""

from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[2] / "alembic/versions/0177_workbench_lesson_correction_applications.py"


def test_additive_receipt_is_separate_immutable_owned_digest_record():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0177"' in source and 'down_revision = "0176"' in source
    assert "workbench_lesson_correction_applications" in source
    assert "plan_id uuid PRIMARY KEY" in source
    assert "ON DELETE CASCADE" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "SECURITY INVOKER SET search_path=pg_catalog" in source
    assert "GRANT SELECT,INSERT,DELETE" in source
    assert "GRANT UPDATE" not in source
    assert "NEW.applied_at := clock_timestamp()" in source
    assert "p.status='ready'" in source
    assert "p.tenant_id=NEW.tenant_id" in source and "p.actor_id=NEW.actor_id" in source
    assert "l.tenant_id=NEW.tenant_id" in source and "c.status='draft'" in source
    assert "p.fingerprint=NEW.fingerprint" in source
    assert "sha256(convert_to" in source
    assert "p.expires_at>clock_timestamp()" in source
    assert "requires an empty table" in source
    assert "ALTER TABLE" not in source.replace("ALTER TABLE {table}", "")


def test_exact_tenant_purge_removes_receipts_before_preview_parent():
    root = MIGRATION.parents[2]
    source = (root / "app/modules/admin/superadmin/service.py").read_text(encoding="utf-8")
    child = "DELETE FROM workbench_lesson_correction_applications WHERE tenant_id = :tenant_id"
    parent = "DELETE FROM workbench_lesson_correction_plans WHERE tenant_id = :tenant_id"
    assert child in source
    assert source.index(child) < source.index(parent)
