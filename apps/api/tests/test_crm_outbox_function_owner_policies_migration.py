from __future__ import annotations

from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0110_crm_outbox_function_owner_policies.py"


def test_crm_function_owner_policies_are_linear_and_do_not_broaden_lms_app() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0110"' in source
    assert 'down_revision = "0109"' in source
    assert "crm_enqueue_tenant_lead_outbox(uuid,uuid,jsonb)" in source
    assert "function_owner = 'lms_app'" in source
    assert "tenant_leads_function_owner" in source
    assert "crm_lead_outbox_function_owner" in source
    assert "ALTER ROLE" not in source
    assert "GRANT" not in source


def test_crm_function_owner_policies_have_a_reversible_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "DROP POLICY IF EXISTS crm_lead_outbox_function_owner" in source
    assert "DROP POLICY IF EXISTS tenant_leads_function_owner" in source
    assert "DROP TABLE" not in source
