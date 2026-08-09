from pathlib import Path


def test_crm_outbox_migration_uses_bounded_security_definer_interfaces():
    source = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0094_crm_lead_outbox.py"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE crm_lead_outbox FORCE ROW LEVEL SECURITY" in source
    assert "REVOKE ALL ON TABLE crm_lead_outbox FROM PUBLIC, lms_app" in source
    assert "CREATE POLICY" not in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = public, pg_temp" in source
    assert "crm_claim_lead_outbox" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "claim_token = p_token" in source
    assert "crm_due_lead_outbox" in source
    assert "crm_lead_outbox_summary" in source
    assert "crm_requeue_dead_lead_outbox" in source
    assert "current_setting('app.is_superadmin', true)" in source


def test_crm_outbox_migration_preserves_legacy_capture_and_safe_downgrade():
    source = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0094_crm_lead_outbox.py"
    ).read_text(encoding="utf-8")

    assert "PUBLIC_LEAD_FUNCTION_8" in source
    assert "PUBLIC_LEAD_FUNCTION_9" in source
    assert "old callers still create an outbox" in source
    assert "Restore the exact bounded 0091 behavior" in source
    assert "0094 downgrade blocked: archive and clear crm_lead_outbox first" in source
    assert source.index("0094 downgrade blocked") < source.index(
        "DROP TABLE crm_lead_outbox"
    )
    assert "PERFORM set_config('app.public_lead_insert', 'true', true)" in source
    assert source.index("DROP FUNCTION IF EXISTS crm_claim_lead_outbox") < source.rindex(
        "DROP TABLE crm_lead_outbox"
    )


def test_systemd_recovery_does_not_depend_on_the_celery_broker():
    service = (
        Path(__file__).parents[3]
        / "infra"
        / "systemd"
        / "kamilya-crm-outbox-recovery.service"
    ).read_text(encoding="utf-8")

    assert "app.modules.tenants.crm_outbox_recovery" in service
    assert "celery" not in service.lower()
