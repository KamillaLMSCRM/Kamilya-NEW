from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0165_source_actuality_and_change_reviews.py"
)


def test_source_actuality_migration_is_additive_tenant_scoped_and_force_rls() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0165"' in text
    assert 'down_revision = "0164"' in text
    assert "document_source_policies" in text
    assert "document_change_reviews" in text
    assert text.count("ENABLE ROW LEVEL SECURITY") == 2
    assert text.count("FORCE ROW LEVEL SECURITY") == 2
    assert "current_setting('app.tenant_id',true)" in text
    assert "freeze_document_change_review_resolution" in text
    assert "resolved document change review is immutable" in text
    assert "must be ready before resolution" in text
    assert "u.id=document_change_reviews.decided_by" in text
    assert "u.role='methodologist' AND u.is_active IS TRUE AND u.status='active'" in text
    assert "DROP COLUMN" not in text.upper()
    assert "DROP TABLE" in text  # downgrade only


def test_source_actuality_migration_never_grants_delete_to_runtime_role() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    runtime_grants = [line.strip() for line in text.splitlines() if "GRANT " in line and "lms_app" in line]
    assert runtime_grants
    assert all("DELETE" not in line for line in runtime_grants)
