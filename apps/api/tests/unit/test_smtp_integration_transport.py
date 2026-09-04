from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.modules.integrations import router as integrations_router


@pytest.mark.asyncio
async def test_tenant_smtp_probe_uses_supported_aiosmtplib_send_contract(monkeypatch) -> None:
    tenant_id = UUID("00000000-0000-0000-0000-000000000101")
    user_id = UUID("00000000-0000-0000-0000-000000000102")
    row = SimpleNamespace(config_encrypted=b"opaque", last_test_at=None, last_test_status=None)
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, email="admin@example.kz")
    send = AsyncMock()

    monkeypatch.setattr(integrations_router, "_get_or_404", AsyncMock(return_value=row))
    monkeypatch.setattr(
        integrations_router.crypto,
        "decrypt_config",
        lambda _value: {
            "host": "smtp.example.kz",
            "port": 465,
            "username": "tenant-user",
            "password": "opaque-password",
            "from_addr": "noreply@example.kz",
            "from_name": "Kamilya",
            "use_tls": True,
        },
    )
    monkeypatch.setattr(integrations_router.aiosmtplib, "send", send)

    result = await integrations_router.smtp_test(db=db, user=user)

    assert result.ok is True
    assert result.detail == "sent to admin@example.kz"
    message = send.await_args.args[0]
    assert message["To"] == "admin@example.kz"
    assert message["From"] == "Kamilya <noreply@example.kz>"
    assert send.await_args.kwargs == {
        "hostname": "smtp.example.kz",
        "port": 465,
        "username": "tenant-user",
        "password": "opaque-password",
        "use_tls": True,
        "timeout": 15,
    }
    assert row.last_test_status == "ok"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_smtp_probe_sanitizes_transport_failure(monkeypatch) -> None:
    tenant_id = UUID("00000000-0000-0000-0000-000000000201")
    user_id = UUID("00000000-0000-0000-0000-000000000202")
    row = SimpleNamespace(config_encrypted=b"opaque", last_test_at=None, last_test_status=None)
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, email="admin@example.kz")

    monkeypatch.setattr(integrations_router, "_get_or_404", AsyncMock(return_value=row))
    monkeypatch.setattr(
        integrations_router.crypto,
        "decrypt_config",
        lambda _value: {
            "host": "smtp.example.kz",
            "port": 465,
            "username": "tenant-user",
            "password": "opaque-password",
            "from_addr": "noreply@example.kz",
            "use_tls": True,
        },
    )
    monkeypatch.setattr(
        integrations_router.aiosmtplib,
        "send",
        AsyncMock(side_effect=RuntimeError("provider detail must stay private")),
    )

    with pytest.raises(HTTPException) as caught:
        await integrations_router.smtp_test(db=db, user=user)

    assert caught.value.status_code == 502
    assert caught.value.detail == "SMTP send failed"
    assert row.last_test_status == "failed: RuntimeError"
    audit_row = db.add.call_args.args[0]
    assert audit_row.metadata_json == {"error_type": "RuntimeError"}
    db.commit.assert_awaited_once()
