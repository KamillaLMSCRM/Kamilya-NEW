from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0116_assignment_access_lookup_function_owner_policy.py"
)


def test_assignment_access_lookup_owner_policy_is_bounded_and_linear() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0116"' in source
    assert 'down_revision = "0115"' in source
    assert "lookup_assignment_access_tenant_by_token(text)" in source
    assert "assignment_access_lookup_function_owner" in source
    assert "FOR SELECT TO %I USING (true)" in source
    assert "function_owner = 'lms_app'" in source
    assert "GRANT EXECUTE ON FUNCTION" in source
    assert "TO lms_app" in source
    assert "GRANT SELECT" not in source
    assert "ALTER ROLE" not in source
    assert "BYPASSRLS" not in source


def test_assignment_access_lookup_owner_policy_has_reversible_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "DROP POLICY IF EXISTS assignment_access_lookup_function_owner" in source
    assert "DROP FUNCTION" not in source
    assert "DROP TABLE" not in source
