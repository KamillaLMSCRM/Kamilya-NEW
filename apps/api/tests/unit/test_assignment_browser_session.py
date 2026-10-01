from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.db import get_db
from app.modules.auth import router as auth_router
from app.modules.auth.browser_session import BrowserSessionPolicy


def policy():
    return BrowserSessionPolicy(
        environment="test", deployment_environment="kz-production",
        application_origin="https://app.kml.kz", trusted_origins=["https://app.kml.kz"],
        cookie_profile="same_site", cookie_secure=True,
        allow_legacy_refresh_body=False, refresh_max_age_seconds=8 * 3600,
    )


@pytest.mark.parametrize("valid", [True, False])
def test_assignment_restore_never_falls_back_to_previous_methodologist(monkeypatch, valid):
    student = {"role": "student", "roles": ["student"], "user_id": "learner"}
    restored = ("same-bounded-jwt", student, 123) if valid else None
    restore = AsyncMock(return_value=restored)
    monkeypatch.setattr(auth_router, "restore_assignment_session", restore)
    ordinary_refresh = AsyncMock(return_value=("staff-jwt", "staff-refresh", {"role": "methodologist"}))
    monkeypatch.setattr(auth_router, "refresh_access_token", ordinary_refresh)
    monkeypatch.setattr(auth_router, "get_browser_session_policy", policy)
    db = SimpleNamespace(commit=AsyncMock())

    async def fake_db():
        yield db

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as client:
        client.cookies.set("kamilya_refresh", "prior-methodologist-cookie")
        client.cookies.set("kamilya_assignment", "same-bounded-jwt")
        for _ in range(2):
            response = client.post("/api/v1/auth/refresh", json={})
            assert response.status_code == (200 if valid else 401)
            if valid:
                assert response.json()["access_token"] == "same-bounded-jwt"
                assert response.json()["expires_in"] == 123
                assert response.json()["user"] == student
            assert "set-cookie" not in response.headers
    ordinary_refresh.assert_not_awaited()
    assert restore.await_count == 2


def test_assignment_cookie_keeps_fail_closed_marker_and_security_scope():
    from fastapi import Response

    session_policy = policy()
    issued, cleared = Response(), Response()
    session_policy.set_assignment_cookie(issued, "bounded-jwt")
    session_policy.clear_assignment_cookie(cleared)
    for response in (issued, cleared):
        cookie = response.headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/api/v1/auth"):
            assert attribute in cookie
        assert "Domain=" not in cookie
    assert "Max-Age=28800" in issued.headers["set-cookie"]
    assert "Max-Age=0" in cleared.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "credential", "policy", "role", "tenant", "inactive"])
async def test_restore_checks_exact_cookie_identity_policy_and_unchanged_ttl(monkeypatch, failure):
    from app.modules.enrollments import access_service

    tenant_id, user_id, enrollment_id, course_id = uuid4(), uuid4(), uuid4(), uuid4()
    token = create_access_token({
        "sub": str(user_id), "tenant_id": str(tenant_id), "active_role": "student",
        "auth_method": "assignment_access", "assignment_access_credential_id": str(uuid4()),
        "assignment_access_enrollment_id": str(enrollment_id),
    }, expires_delta=timedelta(seconds=125))
    principal = SimpleNamespace(
        id=user_id, tenant_id=tenant_id, role="student", status="active",
        assignment_access_enrollment_id=enrollment_id,
    )
    if failure == "role":
        principal.role = "methodologist"
    if failure == "tenant":
        principal.tenant_id = uuid4()
    if failure == "inactive":
        principal.status = "inactive"
    validate = AsyncMock(return_value=principal)
    if failure == "credential":
        validate.side_effect = HTTPException(status_code=401, detail="revoked")
    monkeypatch.setattr(auth_router, "get_current_user", validate)
    read_policy = AsyncMock()
    if failure == "policy":
        read_policy.side_effect = access_service.AssignmentWindowExpiredError("expired", datetime.now(UTC))
    monkeypatch.setattr(access_service, "require_assignment_enrollment_read_access", read_policy)
    monkeypatch.setattr(auth_router, "build_user_payload", AsyncMock(return_value={"role": "methodologist", "roles": ["student", "methodologist"]}))
    db = SimpleNamespace(scalar=AsyncMock(return_value=course_id))
    restored = await auth_router.restore_assignment_session(db, token)
    assert validate.call_args.args[0].credentials == token
    if failure:
        assert restored is None
        return
    assert restored is not None
    returned_token, user, expires_in = restored
    assert returned_token == token
    assert 120 <= expires_in <= 125
    assert user["role"] == "student"
    assert user["roles"] == ["student"]
    assert user["assignment_access_enrollment_id"] == str(enrollment_id)
    read_policy.assert_awaited_once_with(
        db, user_id=user_id, tenant_id=tenant_id, course_id=course_id, enrollment_id=enrollment_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["expired", "ordinary", "malformed", "impersonated", "wrong_role"])
async def test_invalid_cookie_fails_before_any_identity_read(monkeypatch, kind):
    claims = {"sub": str(uuid4()), "tenant_id": str(uuid4()), "active_role": "student", "auth_method": "assignment_access"}
    if kind == "ordinary":
        claims.pop("auth_method")
    if kind == "impersonated":
        claims["impersonated_by"] = str(uuid4())
    if kind == "wrong_role":
        claims["active_role"] = "methodologist"
    token = "invalid-signature" if kind == "malformed" else create_access_token(
        claims, expires_delta=timedelta(seconds=-1 if kind == "expired" else 60),
    )
    validate = AsyncMock()
    monkeypatch.setattr(auth_router, "get_current_user", validate)
    assert await auth_router.restore_assignment_session(SimpleNamespace(), token) is None
    validate.assert_not_awaited()


def test_regular_session_issuance_clears_assignment_context():
    from fastapi import Response

    response = Response()
    policy().set_refresh_cookie(response, "regular-refresh")
    cookies = response.headers.getlist("set-cookie")
    assert any("kamilya_assignment=" in cookie and "Max-Age=0" in cookie for cookie in cookies)


def test_partitioned_assignment_cookie_set_and_clear_match():
    from fastapi import Response

    session_policy = policy()
    session_policy.cookie_profile = "cross_site"
    for clear in (False, True):
        response = Response()
        if clear:
            session_policy.clear_assignment_cookie(response)
        else:
            session_policy.set_assignment_cookie(response, "bounded-jwt")
        cookie = response.headers["set-cookie"]
        assert "SameSite=none" in cookie and "Partitioned" in cookie and "Secure" in cookie


@pytest.mark.parametrize("origin", ["https://evil.example", None])
def test_exchange_browser_boundary_precedes_database_effects(monkeypatch, origin):
    from app.modules.enrollments import router as enrollment_router

    session_policy = policy()
    session_policy.is_production = True
    monkeypatch.setattr(enrollment_router, "get_browser_session_policy", lambda: session_policy)
    calls = []

    async def fake_db():
        calls.append("db")
        yield SimpleNamespace()

    app = FastAPI()
    app.include_router(enrollment_router.public_access_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assignment-access/opaque/exchange", json={"pin": "123456"},
            headers={"Origin": origin} if origin else {},
        )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert calls == []


def test_assignment_context_cannot_exit_to_prior_platform_cookie(monkeypatch):
    monkeypatch.setattr(auth_router, "get_browser_session_policy", policy)
    ordinary = AsyncMock()
    monkeypatch.setattr(auth_router, "refresh_access_token", ordinary)

    async def fake_db():
        yield SimpleNamespace()

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as client:
        client.cookies.set("kamilya_assignment", "expired-assignment")
        client.cookies.set("kamilya_refresh", "platform")
        response = client.post("/api/v1/auth/exit-impersonation", json={})
    assert response.status_code == 403
    ordinary.assert_not_awaited()
