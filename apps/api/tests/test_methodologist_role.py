"""The learning-content owner has one canonical role: methodologist."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.auth import ROLES, require_role


@pytest.mark.asyncio
async def test_methodologist_passes_methodologist_guard():
    checker = require_role("methodologist")
    user = SimpleNamespace(role="methodologist", is_active=True)

    assert await checker(user) is user


def test_methodologist_is_a_persistable_learning_role():
    assert "methodologist" in ROLES


@pytest.mark.asyncio
async def test_methodologist_does_not_gain_admin_access():
    checker = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker(SimpleNamespace(role="methodologist", is_active=True))
    assert exc_info.value.status_code == 403
