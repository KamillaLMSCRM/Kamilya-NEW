"""Static safety contract for the additive organization-unit migration."""

from pathlib import Path

from app.models.department import Department

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0112_organization_units.py"


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_department_model_exposes_organization_unit_compatibility_fields():
    assert Department.unit_type is not None
    assert Department.normalized_name is not None
    assert Department.external_key is not None
    assert Department.is_active is not None
    assert Department.archived_at is not None
    assert Department.source_metadata is not None
    assert Department.legacy_root is not None


def test_migration_is_linear_and_preserves_the_existing_table():
    source = _source()

    assert 'revision = "0112"' in source
    assert 'down_revision = "0111"' in source
    assert 'op.create_table("departments"' not in source
    assert 'op.drop_table("departments"' not in source
    assert 'op.drop_constraint("uq_departments_tenant_slug"' not in source
    assert "uq_departments_tenant_slug" in source


def test_migration_adds_parent_scoped_identity_and_legacy_compatibility():
    source = _source()

    for column in (
        "unit_type",
        "normalized_name",
        "external_key",
        "is_active",
        "archived_at",
        "source_metadata",
        "legacy_root",
    ):
        assert f'"{column}"' in source

    assert "uq_departments_active_root_name" in source
    assert "uq_departments_active_child_name" in source
    assert "uq_departments_tenant_external_key" in source
    assert 'sa.text("parent_id IS NULL AND is_active")' in source
    assert 'sa.text("parent_id IS NOT NULL AND is_active")' in source
    assert 'sa.text("external_key IS NOT NULL")' in source


def test_migration_enforces_hierarchy_and_tenant_ownership_in_database():
    source = _source()

    assert "ck_departments_unit_type" in source
    assert "ck_departments_branch_root" in source
    assert "ck_departments_department_parent" in source
    assert "ck_departments_archive_state" in source
    assert "validate_organization_unit_ownership" in source
    assert "organization unit parent tenant mismatch" in source
    assert "department parent must be an active branch" in source
    assert "organization unit hierarchy cycle" in source
    assert "organization unit head tenant mismatch" in source


def test_migration_keeps_force_rls_and_runtime_grants_closed():
    source = _source()

    assert "ALTER TABLE departments ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE departments FORCE ROW LEVEL SECURITY" in source
    assert "REVOKE ALL ON TABLE departments FROM PUBLIC, lms_app" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON departments TO lms_app" in source
    assert "tenant_organization_units_isolation" in source
    assert "NULLIF(current_setting('app.tenant_id', true), '')::uuid" in source


def test_migration_temporarily_unforces_rls_for_owner_backfill():
    source = _source()
    disable = source.index("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY")
    backfill = source.index("UPDATE departments")
    restore = source.index("ALTER TABLE departments FORCE ROW LEVEL SECURITY", backfill)

    assert disable < backfill < restore


def test_downgrade_refuses_to_erase_canonical_organization_semantics():
    source = _source()

    assert "0112 downgrade refused" in source
    assert "source_metadata->>'origin'" in source
    assert "legacy_migration" in source
