from pathlib import Path

MIGRATION = Path("alembic/versions/0120_kiosk_user_pin_credentials.py")


def test_kiosk_pin_migration_is_linear_tenant_scoped_and_ownership_checked() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0120"' in source
    assert 'down_revision = "0119"' in source
    assert "validate_kiosk_user_credential_ownership" in source
    assert "learner_tenant <> NEW.tenant_id" in source
    assert "issuer_tenant <> NEW.tenant_id" in source
    assert "issuer_is_platform_superadmin" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "tenant_kiosk_user_credentials_isolation" in source
    assert "GRANT SELECT, INSERT, UPDATE" in source
    assert 'ondelete="RESTRICT"' in source
    assert "UPDATE kiosk_access_logs" in source
    assert "repeat('*', length(btrim(personnel_number)) - 2)" in source


def test_kiosk_pin_migration_downgrade_refuses_to_drop_live_credentials() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "0120 downgrade refused: kiosk credentials exist" in source
    assert "IF EXISTS (SELECT 1 FROM kiosk_user_credentials LIMIT 1)" in source


def test_public_kiosk_contract_requires_pin_and_scoped_token() -> None:
    router = Path("app/modules/users/kiosk_router.py").read_text(encoding="utf-8")
    service = Path("app/modules/users/kiosk_service.py").read_text(encoding="utf-8")

    assert 'pin: str = Field(..., min_length=6, max_length=6' in router
    assert "payload.pin" in router
    assert 'token_type="kiosk_access"' in service
    assert "KIOSK_PIN_MAX_ATTEMPTS = 5" in service
    assert "KIOSK_PIN_LOCKOUT = timedelta(minutes=15)" in service
    assert "pn={pn}" not in service
