from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.users.router import (
    get_current_user_profile,
    update_current_user_profile,
)
from app.modules.users.schemas import UserUpdate


def _impersonated_user() -> SimpleNamespace:
    return SimpleNamespace(
        id="operator-id",
        tenant_id="tenant-id",
        role="methodologist",
        is_impersonating=True,
    )


@pytest.mark.asyncio
async def test_impersonated_profile_read_is_explicitly_rejected_before_operator_lookup() -> None:
    db = SimpleNamespace(get=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_profile(db=db, user=_impersonated_user())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Profile is unavailable while impersonating"
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_impersonated_profile_update_cannot_modify_platform_operator() -> None:
    db = SimpleNamespace(get=AsyncMock(), flush=AsyncMock(), refresh=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await update_current_user_profile(
            req=UserUpdate(first_name="Changed"),
            db=db,
            user=_impersonated_user(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Profile is unavailable while impersonating"
    db.get.assert_not_awaited()
    db.flush.assert_not_awaited()
