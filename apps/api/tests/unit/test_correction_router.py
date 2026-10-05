from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, Response
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core import auth
from app.core.db import get_db
from app.modules.methodologist_workbench import correction_router as router
from app.modules.methodologist_workbench.assignment_service import WorkbenchNotFound
from app.modules.methodologist_workbench.correction_schemas import (
    CorrectionApplicationResponse,
    CorrectionPreviewRequest,
    CorrectionPreviewResponse,
)


def _settings(workbench: bool = True, correction: bool = True):
    return SimpleNamespace(
        METHODOLOGIST_WORKBENCH_ENABLED=workbench,
        METHODOLOGIST_LESSON_CORRECTION_ENABLED=correction,
    )


def _user(**changes):
    values = {
        "id": UUID(int=2),
        "tenant_id": UUID(int=1),
        "role": "methodologist",
        "is_impersonating": False,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _request(**changes):
    values = {
        "request_key": uuid4(),
        "lesson_id": UUID(int=5),
        "instruction": "Make this clearer",
        "locale": "en",
    }
    values.update(changes)
    return CorrectionPreviewRequest(**values)


@pytest.mark.parametrize("workbench,correction", [(False, False), (False, True), (True, False)])
def test_context_requires_both_flags_and_no_store(monkeypatch, workbench, correction):
    monkeypatch.setattr(router, "get_settings", lambda: _settings(workbench, correction))
    response = Response()
    with pytest.raises(HTTPException) as error:
        router._context(_user(), response)
    assert error.value.status_code == 404
    assert error.value.detail == "lesson_correction_disabled"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("tenant,impersonating", [(None, False), (UUID(int=1), True)])
def test_context_denies_missing_tenant_or_impersonation(monkeypatch, tenant, impersonating):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    response = Response()
    with pytest.raises(HTTPException) as error:
        router._context(_user(tenant_id=tenant, is_impersonating=impersonating), response)
    assert error.value.status_code == 403
    assert error.value.detail == "workbench_context_denied"
    assert response.headers["Cache-Control"] == "no-store"


def test_request_has_no_client_authority_fields():
    with pytest.raises(ValidationError):
        _request(tenant_id=UUID(int=9))


@pytest.mark.asyncio
async def test_create_returns_ready_payload_and_no_store_without_domain_write(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    expected = CorrectionPreviewResponse(
        plan_id=UUID(int=10),
        lesson_id=UUID(int=5),
        state="ready",
        expires_at=datetime.now(UTC),
        fingerprint="a" * 64,
    )

    async def create(*_args, **_kwargs):
        return expected

    monkeypatch.setattr(router, "create_correction_preview", create)
    db = SimpleNamespace(rollback=AsyncMock())
    response = Response()
    result = await router.create_preview(_request(), response, db, _user())
    assert result == expected
    assert response.headers["Cache-Control"] == "no-store"
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_does_not_call_provider_or_write_and_sets_no_store(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    provider = AsyncMock()
    reader = AsyncMock(
        return_value=CorrectionPreviewResponse(
            plan_id=UUID(int=10),
            lesson_id=UUID(int=5),
            state="failed",
            expires_at=datetime.now(UTC),
            error_code="proposal_unavailable",
        )
    )
    monkeypatch.setattr(router, "get_correction_preview", reader)
    db = SimpleNamespace(rollback=AsyncMock(), provider=provider)
    response = Response()
    result = await router.read_preview(UUID(int=10), response, db, _user())
    assert result.state == "failed"
    reader.assert_awaited_once()
    provider.assert_not_awaited()
    assert response.headers["Cache-Control"] == "no-store"


def test_fixed_error_mapping_never_reflects_exception_text():
    error = router._error(RuntimeError("private provider token and SQL details"))
    assert error.status_code == 409
    assert error.detail == "lesson_correction_conflict"
    assert "private" not in error.detail


def test_routes_preserve_preview_and_add_only_explicit_apply_and_receipt():
    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.router.routes}
    assert ("/lesson-correction-previews", ("POST",)) in paths
    assert ("/lesson-correction-previews/{plan_id}", ("GET",)) in paths
    assert ("/lesson-correction-previews/{plan_id}/apply", ("POST",)) in paths
    assert ("/lesson-correction-previews/{plan_id}/application", ("GET",)) in paths
    assert len(paths) == 4


def _asgi_app(monkeypatch, user):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")

    async def current_active_user():
        return user

    async def db_override():
        yield SimpleNamespace(rollback=AsyncMock())

    app.dependency_overrides[auth.get_current_active_user] = current_active_user
    app.dependency_overrides[get_db] = db_override
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [("POST", "/api/v1/lesson-correction-previews"), ("GET", f"/api/v1/lesson-correction-previews/{UUID(int=10)}")],
)
async def test_real_asgi_feature_off_returns_404(monkeypatch, method, path):
    monkeypatch.setattr(router, "get_settings", lambda: _settings(False, False))
    app = _asgi_app(monkeypatch, _user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await (
            client.post(path, json=_request().model_dump(mode="json")) if method == "POST" else client.get(path)
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "lesson_correction_disabled"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "student"])
async def test_real_asgi_role_gate_rejects_admin_and_student(monkeypatch, role):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    app = _asgi_app(monkeypatch, _user(role=role))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/lesson-correction-previews/{UUID(int=10)}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_real_asgi_methodologist_success_is_no_store(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    expected = CorrectionPreviewResponse(
        plan_id=UUID(int=10),
        lesson_id=UUID(int=5),
        state="ready",
        expires_at=datetime.now(UTC),
        fingerprint="a" * 64,
    )
    service_call = AsyncMock(return_value=expected)
    monkeypatch.setattr(router, "create_correction_preview", service_call)
    app = _asgi_app(monkeypatch, _user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/lesson-correction-previews", json=_request().model_dump(mode="json"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["state"] == "ready"
    service_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_asgi_extra_authority_body_is_422(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    app = _asgi_app(monkeypatch, _user())
    body = _request().model_dump(mode="json") | {"tenant_id": str(UUID(int=99))}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/lesson-correction-previews", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_real_asgi_foreign_resource_is_safe_404(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        router, "create_correction_preview", AsyncMock(side_effect=WorkbenchNotFound("private details"))
    )
    app = _asgi_app(monkeypatch, _user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/lesson-correction-previews", json=_request().model_dump(mode="json"))
    assert response.status_code == 404
    assert response.json()["detail"] == "resource_not_found"


@pytest.mark.asyncio
async def test_real_asgi_apply_route_remains_hidden_when_feature_off(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings(False, False))
    app = _asgi_app(None, _user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/lesson-correction-previews/{UUID(int=10)}/apply",
            json={"plan_id": str(UUID(int=10)), "revision": 1, "fingerprint": "a" * 64},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_real_asgi_explicit_apply_and_receipt_return_same_no_store_result(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    expected = CorrectionApplicationResponse(
        plan_id=UUID(int=10),
        lesson_id=UUID(int=5),
        course_id=UUID(int=3),
        revision=1,
        fingerprint="a" * 64,
        before_sha256="b" * 64,
        after_sha256="c" * 64,
        applied_at=datetime.now(UTC),
    )
    call = AsyncMock(return_value=expected)
    monkeypatch.setattr(router, "apply_correction_preview", call, raising=False)
    monkeypatch.setattr(router, "get_correction_application", AsyncMock(return_value=expected), raising=False)
    app = _asgi_app(None, _user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        applied = await client.post(
            f"/api/v1/lesson-correction-previews/{UUID(int=10)}/apply",
            json={"plan_id": str(UUID(int=10)), "revision": 1, "fingerprint": "a" * 64},
        )
        loaded = await client.get(f"/api/v1/lesson-correction-previews/{UUID(int=10)}/application")
    assert applied.status_code == loaded.status_code == 200
    assert applied.json() == loaded.json() == expected.model_dump(mode="json")
    assert applied.headers["cache-control"] == loaded.headers["cache-control"] == "no-store"
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_asgi_apply_mismatched_path_body_never_calls_writer(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: _settings())
    call = AsyncMock(side_effect=AssertionError("writer must not be reached"))
    monkeypatch.setattr(router, "apply_correction_preview", call, raising=False)
    app = _asgi_app(None, _user())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/lesson-correction-previews/{UUID(int=10)}/apply",
            json={"plan_id": str(UUID(int=11)), "revision": 1, "fingerprint": "a" * 64},
        )
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    call.assert_not_awaited()
