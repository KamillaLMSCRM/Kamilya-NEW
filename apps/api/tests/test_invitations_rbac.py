"""Focused invitation RBAC and lifecycle regression coverage."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth import require_role
from app.modules.users.schemas import InvitationBulkCreateRequest


def _user(*, tenant_id=None, role="methodologist"):
    return SimpleNamespace(id=uuid4(), tenant_id=tenant_id or uuid4(), role=role)


@pytest.mark.asyncio
async def test_methodologist_passes_invitation_role_guard():
    checker = require_role("methodologist")
    user = _user()

    assert await checker(user) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "org_admin", "student"])
async def test_non_owning_roles_are_forbidden_from_invitation_mutations(role):
    checker = require_role("methodologist")

    with pytest.raises(HTTPException) as exc_info:
        await checker(_user(role=role))

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_methodologist_can_create_student_invitation_in_non_demo_tenant():
    from app.modules.users.router import bulk_invite_users

    user = _user()
    db = AsyncMock()
    created = {
        "created": [{
            "email": "learner@example.kz",
            "invitation_id": uuid4(),
            "invite_url": "https://app.kml.kz/accept-invite?token=test",
            "expires_at": "2026-07-26T00:00:00Z",
        }],
        "skipped_existing": [],
        "invalid": [],
    }

    with (
        patch("app.core.demo_limits.assert_can_send_invite", new=AsyncMock()) as demo_guard,
        patch("app.core.trial_limits.assert_can_create_learners", new=AsyncMock()) as learner_guard,
        patch("app.modules.users.router.bulk_create_invitations", new=AsyncMock(return_value=created)) as create,
    ):
        response = await bulk_invite_users(
            payload=InvitationBulkCreateRequest(items=[{"email": "learner@example.kz"}]),
            db=db,
            user=user,
        )

    demo_guard.assert_awaited_once_with(db, user.tenant_id)
    learner_guard.assert_awaited_once_with(db, user.tenant_id, requested=1)
    create.assert_awaited_once()
    assert response.created[0].email == "learner@example.kz"
    assert response.created[0].invite_url.endswith("token=test")


@pytest.mark.asyncio
async def test_cross_tenant_resend_is_not_disclosed():
    from app.modules.users.invitations_service import resend_invitation

    tenant_a, tenant_b = uuid4(), uuid4()
    invitation = SimpleNamespace(id=uuid4(), tenant_id=tenant_b)
    db = SimpleNamespace(get=AsyncMock(return_value=invitation))

    with pytest.raises(HTTPException) as exc_info:
        await resend_invitation(db, tenant_a, invitation.id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Invitation not found"


@pytest.mark.asyncio
async def test_expired_invitation_can_be_resent_once_then_old_link_is_superseded():
    from app.modules.users.invitations_service import resend_invitation

    tenant_id = uuid4()
    old = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="learner@example.kz",
        first_name="",
        last_name="",
        role="student",
        invited_by=uuid4(),
        user_id=uuid4(),
        status="expired",
        superseded_by=None,
    )
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = None
    db = SimpleNamespace(
        get=AsyncMock(return_value=old),
        execute=AsyncMock(return_value=settings_result),
        add=MagicMock(),
        commit=AsyncMock(),
    )

    result = await resend_invitation(db, tenant_id, old.id, base_url="https://app.kml.kz")

    assert old.status == "superseded"
    assert old.superseded_by == result["invitation_id"]
    assert result["invite_url"].startswith("https://app.kml.kz/accept-invite?token=")
    db.commit.assert_awaited_once()

    with pytest.raises(HTTPException) as exc_info:
        await resend_invitation(db, tenant_id, old.id)

    assert exc_info.value.status_code == 409
