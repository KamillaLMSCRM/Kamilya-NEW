"""Static migration-shape tests for the organization course rule table."""
from pathlib import Path


def test_organization_rule_migration_has_required_tenant_guards():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0076_organization_course_rules.py"
    content = migration.read_text(encoding="utf-8")

    assert 'revision = "0076"' in content
    assert 'down_revision = "0075"' in content
    assert '"organization_course_rules"' in content
    assert '"uq_organization_course_rules_tenant_course"' in content
    assert 'ForeignKey("tenants.id"' in content
    assert 'ForeignKey("courses.id"' in content
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "FORCE ROW LEVEL SECURITY" in content
    assert "CREATE POLICY tenant_isolation" in content
    assert "validate_organization_course_rule_parent" in content
