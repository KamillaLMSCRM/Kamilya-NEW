"""Database-free unit contracts for certificate download routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse, Response

from app.modules.certificates import router


def _user(**overrides):
    values = {"id": uuid4(), "tenant_id": uuid4(), "role": "student"}
    values.update(overrides)
    return SimpleNamespace(**values)


def _certificate(user, **overrides):
    values = {
        "id": uuid4(),
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "enrollment_id": None,
        "certificate_number": "KML-2026-41482FABAE33",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_supabase_direct_streams_integrity_checked_pdf_without_signed_url(monkeypatch):
    user = _user()
    cert = _certificate(user)
    pdf = b"%PDF-1.7\ncertificate-integrity\n%%EOF"
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=cert))
    read = AsyncMock(return_value=pdf)
    signed = AsyncMock(side_effect=AssertionError("direct download must not sign a URL"))
    monkeypatch.setattr(router, "read_pdf_bytes", read)
    monkeypatch.setattr(router, "get_pdf_url", signed)
    monkeypatch.setattr(router, "get_storage", lambda: SimpleNamespace(name="supabase"))

    result = await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=True)

    assert isinstance(result, Response)
    assert result.body == pdf
    assert result.media_type == "application/pdf"
    assert result.headers["content-disposition"] == (
        'attachment; filename="certificate-KML-2026-41482FABAE33.pdf"'
    )
    read.assert_awaited_once()
    signed.assert_not_awaited()


@pytest.mark.asyncio
async def test_supabase_legacy_default_remains_redirect(monkeypatch):
    user = _user()
    cert = _certificate(user)
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=cert))
    signed = AsyncMock(return_value="https://storage.example.test/signed.pdf")
    monkeypatch.setattr(router, "get_pdf_url", signed)
    monkeypatch.setattr(router, "get_storage", lambda: SimpleNamespace(name="supabase"))

    result = await router.download_certificate_pdf(uuid4(), MagicMock(), user)

    assert isinstance(result, RedirectResponse)
    assert result.status_code == 302
    assert result.headers["location"] == "https://storage.example.test/signed.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_local_backend_streams_bytes_for_default_and_direct(monkeypatch, direct):
    user = _user()
    cert = _certificate(user)
    pdf = b"%PDF-local\n%%EOF"
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=cert))
    read = AsyncMock(return_value=pdf)
    monkeypatch.setattr(router, "read_pdf_bytes", read)
    monkeypatch.setattr(router, "get_storage", lambda: SimpleNamespace(name="local"))

    result = await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=direct)

    assert isinstance(result, Response)
    assert result.body == pdf
    read.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_denies_missing_or_out_of_scope_certificate_before_pdf_read(monkeypatch):
    user = _user()
    read = AsyncMock(side_effect=AssertionError("bytes must not be read"))
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=None))
    monkeypatch.setattr(router, "read_pdf_bytes", read)
    monkeypatch.setattr(router, "get_pdf_url", AsyncMock(side_effect=AssertionError("must not sign")))

    with pytest.raises(HTTPException) as exc_info:
        await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=True)
    assert exc_info.value.status_code == 404
    read.assert_not_awaited()

    foreign = _certificate(_user(), tenant_id=user.tenant_id)
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=foreign))
    with pytest.raises(HTTPException) as exc_info:
        await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=True)
    assert exc_info.value.status_code == 404
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthorized_role_denies_before_pdf_read(monkeypatch):
    owner = _user()
    user = _user(role="student")
    cert = _certificate(owner, tenant_id=user.tenant_id)
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=cert))
    read = AsyncMock(side_effect=AssertionError("bytes must not be read"))
    monkeypatch.setattr(router, "read_pdf_bytes", read)

    with pytest.raises(HTTPException) as exc_info:
        await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=True)
    assert exc_info.value.status_code == 404
    read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("pdf_value", [None, b""])
async def test_missing_or_corrupt_pdf_is_server_error(monkeypatch, pdf_value):
    user = _user()
    cert = _certificate(user)
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=cert))
    monkeypatch.setattr(router, "get_storage", lambda: SimpleNamespace(name="supabase"))
    monkeypatch.setattr(router, "read_pdf_bytes", AsyncMock(return_value=pdf_value))

    with pytest.raises(HTTPException) as exc_info:
        await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=True)
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_integrity_reader_failure_is_server_error(monkeypatch):
    user = _user()
    monkeypatch.setattr(router, "get_certificate", AsyncMock(return_value=_certificate(user)))
    monkeypatch.setattr(router, "get_storage", lambda: SimpleNamespace(name="supabase"))
    monkeypatch.setattr(router, "read_pdf_bytes", AsyncMock(side_effect=ValueError("invalid PDF")))

    with pytest.raises(HTTPException) as exc_info:
        await router.download_certificate_pdf(uuid4(), MagicMock(), user, direct=True)
    assert exc_info.value.status_code == 500
