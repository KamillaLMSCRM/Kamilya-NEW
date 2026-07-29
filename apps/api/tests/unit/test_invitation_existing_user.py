"""Unit coverage for invitations attached to imported staff records."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.users import User, UserInvitation
from app.modules.users.invitations_service import (
    accept_invitation,
    bulk_create_invitations,
)
from app.modules.users.schemas import UserResponse


def _user(*, tenant_id, email, password_hash=None, telegram_id=None, role="student"):
    return User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=email,
        personnel_number="EMP-007",
        first_name="Айжан",
        last_name="Ахметова",
        role=role,
        # Staff import creates an active learning identity even before a
        # password or Telegram account is configured.
        is_active=True,
        status="active",
        password_hash=password_hash,
        telegram_id=telegram_id,
    )


def _bulk_db(*, existing_users=(), pending_invitations=()):
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = list(existing_users)
    pending_result = MagicMock()
    pending_result.all.return_value = [(inv.email,) for inv in pending_invitations]
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = None

    added = []
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[existing_result, pending_result, settings_result]),
        add=MagicMock(side_effect=added.append),
        commit=AsyncMock(),
    )
    return db, added


@pytest.mark.asyncio
async def test_existing_student_without_login_gets_invitation_without_duplicate_user():
    tenant_id = uuid4()
    existing = _user(tenant_id=tenant_id, email="employee@example.kz")
    db, added = _bulk_db(existing_users=[existing])

    result = await bulk_create_invitations(
        db,
        tenant_id,
        invited_by=uuid4(),
        raw_emails=[" EMPLOYEE@example.kz "],
        base_url="https://app.kml.kz",
    )

    assert len(result["created"]) == 1
    invitation = next(item for item in added if isinstance(item, UserInvitation))
    assert not any(isinstance(item, User) for item in added)
    assert invitation.user_id == existing.id
    assert invitation.first_name == existing.first_name
    assert invitation.last_name == existing.last_name
    assert invitation.personnel_number == existing.personnel_number
    assert result["created"][0]["personnel_number"] == existing.personnel_number
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_user_with_login_access_is_skipped():
    tenant_id = uuid4()
    existing = _user(tenant_id=tenant_id, email="employee@example.kz", password_hash="argon-hash")
    db, added = _bulk_db(existing_users=[existing])

    result = await bulk_create_invitations(db, tenant_id, uuid4(), [existing.email])

    assert result["created"] == []
    assert result["skipped_existing"] == [{"email": existing.email, "reason": "already_has_access"}]
    assert added == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_invitation_is_still_skipped_for_existing_staff_user():
    tenant_id = uuid4()
    existing = _user(tenant_id=tenant_id, email="employee@example.kz")
    pending = SimpleNamespace(email=existing.email)
    db, added = _bulk_db(existing_users=[existing], pending_invitations=[pending])

    result = await bulk_create_invitations(db, tenant_id, uuid4(), [existing.email])

    assert result["created"] == []
    assert result["skipped_existing"] == [{"email": existing.email, "reason": "pending_invite_exists"}]
    assert added == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_acceptance_still_activates_the_existing_staff_user():
    tenant_id = uuid4()
    user = _user(tenant_id=tenant_id, email="employee@example.kz")
    invitation = UserInvitation(
        id=uuid4(),
        tenant_id=tenant_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        personnel_number=user.personnel_number,
        role="student",
        invited_by=uuid4(),
        token="existing-staff-token",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_id=user.id,
    )
    token_result = MagicMock()
    token_result.scalar_one_or_none.return_value = invitation
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[token_result, MagicMock()]),
        get=AsyncMock(return_value=user),
        commit=AsyncMock(),
    )

    result = await accept_invitation(
        db,
        invitation.token,
        first_name=user.first_name,
        last_name=user.last_name,
        password="Password123!",
        personnel_number=user.personnel_number,
    )

    assert result["user_id"] == user.id
    assert user.password_hash
    assert user.is_active is True
    assert user.status == "active"
    assert invitation.status == "accepted"
    db.commit.assert_awaited_once()


def test_user_response_exposes_only_login_access_boolean():
    source = _user(tenant_id=uuid4(), email="employee@example.kz", password_hash="secret-hash")
    source.created_at = datetime.now(UTC)

    response = UserResponse.model_validate(source)

    assert response.has_login_access is True
    assert "password_hash" not in response.model_dump()


def test_user_response_reports_telegram_login_without_exposing_secret():
    source = _user(tenant_id=uuid4(), email="employee@example.kz", telegram_id=12345)
    source.created_at = datetime.now(UTC)

    response = UserResponse.model_validate(source)

    assert response.has_login_access is True
    assert "password_hash" not in response.model_dump()


def test_user_response_reports_no_login_access_for_imported_staff():
    source = _user(tenant_id=uuid4(), email="employee@example.kz")
    source.created_at = datetime.now(UTC)

    response = UserResponse.model_validate(source)

    assert response.has_login_access is False
