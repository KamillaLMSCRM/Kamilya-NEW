from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.auth.service import get_user_roles
from app.modules.users.service import assign_role


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar


@pytest.mark.asyncio
async def test_get_user_roles_keeps_primary_role_first():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="admin")
    db = SimpleNamespace(execute=AsyncMock(return_value=_Result([
        ("methodologist",),
        ("admin",),
    ])))

    assert await get_user_roles(db, user) == ["admin", "methodologist"]


@pytest.mark.asyncio
async def test_get_user_roles_supports_platform_account_without_tenant_query():
    user = SimpleNamespace(id=uuid4(), tenant_id=None, role="superadmin")
    db = SimpleNamespace(execute=AsyncMock())

    assert await get_user_roles(db, user) == ["superadmin"]
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_assign_role_adds_role_without_changing_primary_role():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="admin")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_Result()),
        add=lambda value: setattr(db, "added", value),
        flush=AsyncMock(),
    )

    with patch("app.modules.users.service.get_user", AsyncMock(return_value=user)):
        result = await assign_role(db, user.id, user.tenant_id, "methodologist")

    assert result is user
    assert user.role == "admin"
    assert db.added.role == "methodologist"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_role_rejects_duplicate_assignment():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="admin")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_Result(scalar=uuid4())),
        add=lambda value: None,
        flush=AsyncMock(),
    )

    with patch("app.modules.users.service.get_user", AsyncMock(return_value=user)):
        with pytest.raises(ValueError, match="already assigned"):
            await assign_role(db, user.id, user.tenant_id, "admin")
