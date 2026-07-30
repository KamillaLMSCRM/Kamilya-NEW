"""Public invitation view does not leak the full employee email."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.users import User, UserInvitation
from app.modules.users.invitations_service import get_public_invitation
from app.modules.users.schemas import InvitationPublicView


@pytest.mark.asyncio
async def test_public_invitation_returns_read_only_hr_identity_and_masked_email():
    tenant_id = uuid4()
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="employee@example.kz",
        first_name="Айжан",
        last_name="Ахметова",
        role="student",
        is_active=False,
        status="inactive",
    )
    invitation = UserInvitation(
        id=uuid4(),
        tenant_id=tenant_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role="student",
        invited_by=uuid4(),
        token="public-view-token",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_id=user.id,
    )
    invitation_result = MagicMock()
    invitation_result.scalar_one_or_none.return_value = invitation
    tenant_context_result = MagicMock()
    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = SimpleNamespace(
        id=tenant_id,
        name="ТОО Тест",
    )
    course_result = MagicMock()
    course_result.scalars.return_value.all.return_value = ["Вводный курс"]
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                invitation_result,
                tenant_context_result,
                tenant_result,
                course_result,
            ]
        ),
        get=AsyncMock(return_value=user),
        commit=AsyncMock(),
    )

    payload = await get_public_invitation(db, invitation.token)
    response = InvitationPublicView.model_validate(payload)

    assert "email" not in response.model_dump()
    assert response.masked_email == "e*******@example.kz"
    assert response.first_name == "Айжан"
    assert response.last_name == "Ахметова"
    assert response.course_titles == ["Вводный курс"]
