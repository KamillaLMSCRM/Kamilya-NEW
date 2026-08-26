"""Scoped OTP behavior for employee invitation activation."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.auth import email_otp


@pytest.fixture(autouse=True)
def reset_otp_state(monkeypatch):
    email_otp._memory_store.clear()
    email_otp._redis_client = None
    monkeypatch.setattr(email_otp, "_get_redis", AsyncMock(return_value=None))
    yield
    email_otp._memory_store.clear()
    email_otp._redis_client = None


@pytest.mark.asyncio
async def test_invitation_code_is_isolated_from_normal_login_code(monkeypatch):
    generated = iter((111111, 222222))
    monkeypatch.setattr(
        email_otp.secrets,
        "randbelow",
        lambda _limit: next(generated),
    )

    login_code, _ = await email_otp.create_email_code(
        email="employee@example.kz",
        user_id="user-1",
        tenant_id="tenant-1",
        role="student",
    )
    invitation_code, _, created = await email_otp.create_invitation_email_code(
        email="employee@example.kz",
        user_id="user-1",
        tenant_id="tenant-1",
        role="student",
        invitation_id="invite-1",
    )

    assert created is True
    assert login_code != invitation_code
    assert await email_otp.consume_email_code(
        email="employee@example.kz",
        code=login_code,
        purpose="invitation",
        subject_id="invite-1",
    ) is None
    assert await email_otp.consume_email_code(
        email="employee@example.kz",
        code=invitation_code,
        purpose="invitation",
        subject_id="invite-1",
    )
    assert await email_otp.consume_email_code(
        email="employee@example.kz",
        code=login_code,
    )


@pytest.mark.asyncio
async def test_invitation_code_is_destroyed_after_five_failed_attempts(monkeypatch):
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: 123456)
    code, _, _ = await email_otp.create_invitation_email_code(
        email="employee@example.kz",
        user_id="user-1",
        tenant_id="tenant-1",
        role="student",
        invitation_id="invite-1",
    )

    for _ in range(email_otp.EMAIL_CODE_MAX_ATTEMPTS):
        assert await email_otp.consume_email_code(
            email="employee@example.kz",
            code="000000",
            purpose="invitation",
            subject_id="invite-1",
        ) is None

    assert await email_otp.consume_email_code(
        email="employee@example.kz",
        code=code,
        purpose="invitation",
        subject_id="invite-1",
    ) is None


@pytest.mark.asyncio
async def test_invitation_code_respects_resend_cooldown(monkeypatch):
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: 123456)

    first_code, first_ttl, first_created = (
        await email_otp.create_invitation_email_code(
            email="employee@example.kz",
            user_id="user-1",
            tenant_id="tenant-1",
            role="student",
            invitation_id="invite-1",
        )
    )
    second_code, second_ttl, second_created = (
        await email_otp.create_invitation_email_code(
            email="employee@example.kz",
            user_id="user-1",
            tenant_id="tenant-1",
            role="student",
            invitation_id="invite-1",
        )
    )

    assert first_created is True
    assert second_created is False
    assert second_code == first_code
    assert 0 < second_ttl <= first_ttl


@pytest.mark.asyncio
async def test_invitation_code_can_be_invalidated_after_delivery_failure(monkeypatch):
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: 123456)
    code, _, _ = await email_otp.create_invitation_email_code(
        email="employee@example.kz",
        user_id="user-1",
        tenant_id="tenant-1",
        role="student",
        invitation_id="invite-1",
    )

    await email_otp.invalidate_email_code(
        email="employee@example.kz",
        purpose="invitation",
        subject_id="invite-1",
    )

    assert await email_otp.consume_email_code(
        email="employee@example.kz",
        code=code,
        purpose="invitation",
        subject_id="invite-1",
    ) is None


@pytest.mark.asyncio
async def test_registration_code_is_purpose_bound_and_single_use(monkeypatch):
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: 234567)
    code, _, created = await email_otp.create_registration_email_code(
        email="owner@example.kz",
    )

    assert created is True
    assert await email_otp.consume_email_code(
        email="owner@example.kz",
        code=code,
    ) is None
    assert await email_otp.consume_email_code(
        email="owner@example.kz",
        code=code,
        purpose=email_otp.REGISTRATION_EMAIL_CODE_PURPOSE,
    )
    assert await email_otp.consume_email_code(
        email="owner@example.kz",
        code=code,
        purpose=email_otp.REGISTRATION_EMAIL_CODE_PURPOSE,
    ) is None
