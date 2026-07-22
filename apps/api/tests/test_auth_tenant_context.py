from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient

from app.core.auth import create_access_token, get_current_user
from app.core.db import get_db
from app.core.errors import register_error_handlers


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _credentials() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


@pytest.mark.asyncio
async def test_tenant_context_failure_rolls_back_and_rejects_before_user_query():
    tenant_id = uuid4()
    user_id = uuid4()
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=RuntimeError("tenant context unavailable")),
        rollback=AsyncMock(),
    )

    with patch(
        "app.core.auth.decode_token",
        return_value={"sub": str(user_id), "tenant_id": str(tenant_id)},
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=_credentials(), db=db)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Tenant security context unavailable"
    db.rollback.assert_awaited_once()
    assert db.execute.await_count == 1
    assert "set_current_tenant" in str(db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_tenant_context_failure_stops_fastapi_endpoint_execution():
    tenant_id = uuid4()
    user_id = uuid4()
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=RuntimeError("tenant context unavailable")),
        rollback=AsyncMock(),
    )
    endpoint_called = False
    app = FastAPI()
    register_error_handlers(app)

    async def override_db():
        yield db

    @app.get("/protected")
    async def protected(_user=Depends(get_current_user)):  # noqa: B008
        nonlocal endpoint_called
        endpoint_called = True
        return {"ok": True}

    app.dependency_overrides[get_db] = override_db
    token = create_access_token(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "roles": ["student"],
            "active_role": "student",
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": "service_unavailable",
        "message": "Tenant security context unavailable",
    }
    assert endpoint_called is False
    db.rollback.assert_awaited_once()
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_normal_tenant_path_sets_context_before_loading_user():
    tenant_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        role="student",
        is_active=True,
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[object(), _ScalarResult(user)]),
        rollback=AsyncMock(),
    )

    with patch(
        "app.core.auth.decode_token",
        return_value={
            "sub": str(user.id),
            "tenant_id": str(tenant_id),
            "active_role": "student",
        },
    ):
        result = await get_current_user(credentials=_credentials(), db=db)

    assert result is user
    assert db.execute.await_count == 2
    assert "set_current_tenant" in str(db.execute.await_args_list[0].args[0])
    assert "FROM users" in str(db.execute.await_args_list[1].args[0])
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_platform_superadmin_path_enables_superadmin_context():
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=None,
        role="superadmin",
        is_active=True,
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_ScalarResult(user), object()]),
        rollback=AsyncMock(),
    )

    with patch(
        "app.core.auth.decode_token",
        return_value={"sub": str(user.id), "tenant_id": None},
    ):
        result = await get_current_user(credentials=_credentials(), db=db)

    assert result is user
    assert db.execute.await_count == 2
    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert all("set_current_tenant" not in statement for statement in statements)
    assert "app.is_superadmin" in statements[1]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_impersonation_uses_target_tenant_without_superadmin_rls_bypass():
    target_tenant_id = uuid4()
    superadmin = SimpleNamespace(
        id=uuid4(),
        tenant_id=None,
        role="superadmin",
        is_active=True,
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[object(), _ScalarResult(superadmin)]),
        rollback=AsyncMock(),
    )

    with patch(
        "app.core.auth.decode_token",
        return_value={
            "sub": str(superadmin.id),
            "tenant_id": str(target_tenant_id),
            "impersonated_tenant": str(target_tenant_id),
            "impersonated_role": "methodologist",
        },
    ):
        result = await get_current_user(credentials=_credentials(), db=db)

    assert result.is_impersonating is True
    assert result.tenant_id == target_tenant_id
    assert result.role == "methodologist"
    assert db.execute.await_count == 2
    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert "set_current_tenant" in statements[0]
    assert all("app.is_superadmin" not in statement for statement in statements)
    db.rollback.assert_not_awaited()
