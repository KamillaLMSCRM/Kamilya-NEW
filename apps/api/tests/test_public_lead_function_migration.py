from pathlib import Path


def test_public_lead_function_is_security_definer_and_bounded():
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0091_public_lead_insert_function.py"
    )
    source = migration.read_text(encoding="utf-8")

    assert 'revision = "0091"' in source
    assert 'down_revision = "0090"' in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = public, pg_temp" in source
    assert "PERFORM set_config('app.public_lead_insert', 'true', true)" in source
    assert "tenant_id" in source
    assert "NULL" in source
    assert "'landing_form'" in source
    assert "REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE}" in source
    assert "GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE}" in source
    assert "TO lms_app" in source
