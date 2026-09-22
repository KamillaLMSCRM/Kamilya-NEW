"""Static migration contract for manual reassignment occurrence identity."""

from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0162_manual_reassignment_occurrences.py"


def test_manual_reassignment_migration_preserves_tenant_ownership_and_rls_contract():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "previous_enrollment_id" in source
    assert "create_foreign_key" in source
    assert "tenant_id" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "ownership mismatch" in source
    assert "learning_path_assignment_id IS NULL" in source
    assert "source_schema=schema" in source
    assert 'SET search_path="{schema}",pg_temp' in source
    assert "TG_OP = 'UPDATE'" in source
    assert "manual reassignment identity is immutable" in source
    assert "link_validity_minutes" in source
    assert "due_window_minutes" in source
    assert "link_expires_at - created_at" in source
    assert "due_at - created_at" in source
    assert "updated_at <= created_at + interval '1 second'" in source
