"""Invitation endpoints follow the active learning-role contract."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.main import app
from app.modules.users.router import router


def _role_dependency(path: str, method: str):
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
    )
    return next(
        dependency.call
        for dependency in route.dependant.dependencies
        if getattr(dependency.call, "__name__", "") == "role_checker"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_methodologist_active_role_can_use_learner_invitations(method):
    path = "/users/invitations" if method == "GET" else "/users/invitations/bulk"
    checker = _role_dependency(path, method)
    user = SimpleNamespace(role="methodologist")
    assert await checker(user) is user


@pytest.mark.asyncio
async def test_methodologist_invitation_list_request_reaches_static_handler(
):
    class Result:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

        def scalars(self):
            return self

        def all(self):
            return self.value

    class DB:
        def __init__(self):
            self.results = iter([Result(0), Result([])])

        async def execute(self, _query):
            return next(self.results)

    async def override_db():
        yield DB()

    async def override_user():
        return SimpleNamespace(role="methodologist", tenant_id="tenant-id")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_active_user] = override_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/users/invitations?per_page=100")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": 100}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "org_admin", "student"])
async def test_non_learning_roles_cannot_list_learner_invitations(role):
    checker = _role_dependency("/users/invitations", "GET")
    with pytest.raises(HTTPException) as caught:
        await checker(SimpleNamespace(role=role))
    assert caught.value.status_code == 403
