from pathlib import Path


def test_department_repair_migration_normalizes_legacy_positions():
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0079_repair_legacy_position_departments.py"
    )
    content = migration.read_text(encoding="utf-8")

    assert 'revision = "0079"' in content
    assert 'down_revision = "0078"' in content
    assert "ON CONFLICT (tenant_id, slug) DO NOTHING" in content
    assert "lower(trim(p.department))" in content
    assert "department_id = d.id" in content
    assert "d.tenant_id = p.tenant_id" in content
