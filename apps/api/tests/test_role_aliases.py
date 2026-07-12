"""The product names the learning-content role teacher/methodologist."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.auth import LEARNING_CONTENT_ROLES, ROLES, require_role


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_role", ["teacher", "methodologist"])
async def test_learning_roles_are_mutual_aliases(declared_role: str):
    checker = require_role(declared_role)
    user_role = "methodologist" if declared_role == "teacher" else "teacher"
    user = SimpleNamespace(role=user_role, is_active=True)

    assert await checker(user) is user


def test_methodologist_is_a_persistable_learning_role():
    assert LEARNING_CONTENT_ROLES == {"teacher", "methodologist"}
    assert "methodologist" in ROLES


@pytest.mark.asyncio
async def test_learning_role_alias_does_not_grant_admin_access():
    checker = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker(SimpleNamespace(role="teacher", is_active=True))
    assert exc_info.value.status_code == 403
