from pathlib import Path


def test_public_lead_rls_policy_is_bounded_to_transaction_context():
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0090_bound_public_lead_rls.py"
    )
    source = migration.read_text(encoding="utf-8")

    assert 'revision = "0090"' in source
    assert 'down_revision = "0089"' in source
    assert "FOR INSERT" in source
    assert "TO PUBLIC" in source
    assert "tenant_id IS NULL" in source
    assert "source = 'landing_form'" in source
    assert "current_setting('app.public_lead_insert', true) = 'true'" in source
