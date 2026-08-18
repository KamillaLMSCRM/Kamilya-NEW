from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0111_email_login_lookup_function_owner_policy.py"
)


def test_email_login_lookup_owner_policy_is_bounded_and_linear() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0111"' in source
    assert 'down_revision = "0110"' in source
    assert "lookup_login_user_by_email(text)" in source
    assert "users_auth_email_lookup_function_owner" in source
    assert "FOR SELECT TO %I USING (true)" in source
    assert "function_owner = 'lms_app'" in source
    assert "ALTER ROLE" not in source
    assert "BYPASSRLS" not in source


def test_email_login_lookup_owner_policy_has_reversible_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "DROP POLICY IF EXISTS users_auth_email_lookup_function_owner" in source
    assert "DROP FUNCTION" not in source
    assert "DROP TABLE" not in source
