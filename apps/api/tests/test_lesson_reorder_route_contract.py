"""Public route contract for the course editor's lesson-reorder request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.modules.lessons import router as lessons_router_module
from app.modules.lessons.router import router as lessons_router


def test_lesson_reorder_is_published_under_lessons_prefix() -> None:
    routes = [
        route
        for route in lessons_router.routes
        if isinstance(route, APIRoute) and route.path == "/lessons/{module_id}/reorder" and "POST" in route.methods
    ]

    assert len(routes) == 1
    assert routes[0].name == "reorder_lessons"


def test_methodologist_reorders_lessons_through_published_route(monkeypatch) -> None:
    db = object()
    user = SimpleNamespace(role="methodologist", tenant_id="tenant-1")
    reorder_lessons_in_module = AsyncMock()

    async def override_db():
        yield db

    async def override_current_user():
        return user

    monkeypatch.setattr(lessons_router_module, "reorder_lessons_in_module", reorder_lessons_in_module)
    app = FastAPI()
    app.include_router(lessons_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_active_user] = override_current_user

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/lessons/11111111-1111-1111-1111-111111111111/reorder",
            json=[
                "22222222-2222-2222-2222-222222222222",
                "33333333-3333-3333-3333-333333333333",
            ],
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    reorder_lessons_in_module.assert_awaited_once_with(
        db,
        module_id=UUID("11111111-1111-1111-1111-111111111111"),
        ids_order=[
            UUID("22222222-2222-2222-2222-222222222222"),
            UUID("33333333-3333-3333-3333-333333333333"),
        ],
        tenant_id="tenant-1",
    )


@pytest.mark.asyncio
async def test_lesson_reorder_rejects_cross_module_and_partial_lists(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
) -> None:
    from app.modules.lessons.service import reorder_lessons_in_module

    tenant = await make_tenant(name="Scoped lesson reorder")
    author = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, author)
    first_module = await make_module(course, title="First")
    second_module = await make_module(course, title="Second")
    first = await make_lesson(first_module, title="One")
    second = await make_lesson(first_module, title="Two")
    foreign = await make_lesson(second_module, title="Other module")

    with pytest.raises(ValueError, match="every lesson"):
        await reorder_lessons_in_module(
            db_session,
            module_id=first_module.id,
            ids_order=[first.id, foreign.id],
            tenant_id=tenant.id,
        )
    with pytest.raises(ValueError, match="every lesson"):
        await reorder_lessons_in_module(
            db_session,
            module_id=first_module.id,
            ids_order=[first.id],
            tenant_id=tenant.id,
        )

    await reorder_lessons_in_module(
        db_session,
        module_id=first_module.id,
        ids_order=[second.id, first.id],
        tenant_id=tenant.id,
    )
    assert second.order_index == 0
    assert first.order_index == 1
