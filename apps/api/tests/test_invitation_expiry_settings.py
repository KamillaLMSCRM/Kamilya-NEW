from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.tenant_settings import TenantSettings
from app.modules.users.invitations_service import _get_tenant_invite_expiry_days


@pytest.mark.asyncio
async def test_invitation_expiry_reads_tenant_setting() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = TenantSettings(
        tenant_id=uuid4(),
        invite_expiry_days=7,
    )
    db = AsyncMock()
    db.execute.return_value = result

    assert await _get_tenant_invite_expiry_days(db, uuid4()) == 7


@pytest.mark.asyncio
async def test_invitation_expiry_defaults_when_settings_are_absent() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    assert await _get_tenant_invite_expiry_days(db, uuid4()) == 3


def test_tenant_settings_maps_invitation_expiry_column() -> None:
    assert "invite_expiry_days" in TenantSettings.__table__.columns
