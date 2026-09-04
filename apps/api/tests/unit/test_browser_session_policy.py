from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.legal_versions import CURRENT_PRIVACY_CONSENT_VERSION, CURRENT_TERMS_VERSION
from app.modules.auth import router as auth_router
from app.modules.auth import superadmin_login as superadmin_router
from app.modules.auth.browser_session import BrowserSessionPolicy
from app.modules.tenants import router as tenant_router
from app.modules.users import invitations_router

TRUSTED_ORIGINS = ["https://app.kml.kz"]


def _request(*, origin: str | None = None, fetch_site: str | None = None, content_type: str | None = None, cookie: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    for name, value in (
        ("origin", origin),
        ("sec-fetch-site", fetch_site),
        ("content-type", content_type),
        ("cookie", cookie),
    ):
        if value is not None:
            headers.append((name.encode("ascii"), value.encode("ascii")))
    return Request({"type": "http", "method": "POST", "path": "/api/v1/auth/refresh", "headers": headers})


def _policy(**overrides) -> BrowserSessionPolicy:
    values = {
        "environment": "production",
        "deployment_environment": "kz-production",
        "application_origin": "https://app.kml.kz",
        "trusted_origins": TRUSTED_ORIGINS,
        "cookie_profile": "same_site",
        "cookie_secure": True,
        "allow_legacy_refresh_body": False,
        "refresh_max_age_seconds": 30 * 24 * 60 * 60,
    }
    values.update(overrides)
    return BrowserSessionPolicy(**values)


def test_production_accepts_exact_kz_browser_origin() -> None:
    _policy().enforce_request(
        _request(origin="https://app.kml.kz", fetch_site="same-site", content_type="application/json; charset=utf-8")
    )


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "https://app.kml.kz.evil.example", "not-an-origin"])
def test_browser_session_rejects_untrusted_or_malformed_origin(origin: str) -> None:
    with pytest.raises(HTTPException) as caught:
        _policy().enforce_request(_request(origin=origin, content_type="application/json"))
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "browser_origin_forbidden"


def test_production_requires_origin_before_session_work() -> None:
    with pytest.raises(HTTPException) as caught:
        _policy().enforce_request(_request(content_type="application/json"))
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "browser_origin_required"


def test_fetch_metadata_rejects_cross_site_request() -> None:
    with pytest.raises(HTTPException) as caught:
        _policy().enforce_request(
            _request(origin="https://app.kml.kz", fetch_site="cross-site", content_type="application/json")
        )
    assert caught.value.detail["code"] == "cross_site_request_forbidden"


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"])
def test_production_session_mutation_requires_json(content_type: str) -> None:
    with pytest.raises(HTTPException) as caught:
        _policy().enforce_request(_request(origin="https://app.kml.kz", content_type=content_type))
    assert caught.value.status_code == 400
    assert caught.value.detail["code"] == "browser_json_required"


def test_same_site_cookie_set_and_clear_have_matching_security_scope() -> None:
    policy = _policy()
    issued = Response()
    cleared = Response()

    policy.set_refresh_cookie(issued, "opaque-refresh")
    policy.clear_refresh_cookie(cleared)

    issued_cookie = issued.headers["set-cookie"]
    cleared_cookie = cleared.headers["set-cookie"]
    for attribute in ("HttpOnly", "Path=/api/v1/auth", "SameSite=lax", "Secure"):
        assert attribute in issued_cookie
        assert attribute in cleared_cookie
    assert "Partitioned" not in issued_cookie
    assert "Partitioned" not in cleared_cookie
    assert "Domain=" not in issued_cookie
    assert "Max-Age=0" in cleared_cookie


def test_cross_site_cookie_profile_is_partitioned_only_outside_production() -> None:
    policy = _policy(
        environment="production",
        deployment_environment="render-development",
        trusted_origins=["https://kamilya-lms-dev.vercel.app"],
        cookie_profile="cross_site",
    )
    policy.enforce_request(
        _request(
            origin="https://kamilya-lms-dev.vercel.app",
            fetch_site="cross-site",
            content_type="application/json",
        )
    )
    response = Response()
    policy.set_refresh_cookie(response, "opaque-refresh")
    cookie = response.headers["set-cookie"]
    assert "SameSite=none" in cookie
    assert "Secure" in cookie
    assert "Partitioned" in cookie

    with pytest.raises(ValueError, match="cross_site"):
        _policy(cookie_profile="cross_site")


def test_production_requires_secure_cookie_and_forbids_legacy_body_fallback() -> None:
    with pytest.raises(ValueError, match="secure"):
        _policy(cookie_secure=False)
    with pytest.raises(ValueError, match="legacy"):
        _policy(allow_legacy_refresh_body=True)
    with pytest.raises(ValueError, match="HTTPS"):
        _policy(trusted_origins=["http://app.kml.kz"])


@pytest.mark.parametrize(
    "trusted_origin",
    ["https://www.kml.kz", "https://unrelated.example"],
)
def test_kz_production_trusts_only_the_configured_application_origin(trusted_origin: str) -> None:
    with pytest.raises(ValueError, match="PUBLIC_URL"):
        _policy(trusted_origins=[trusted_origin])


def test_explicit_render_development_topology_may_use_its_cross_site_frontend() -> None:
    policy = _policy(
        deployment_environment="render-development",
        trusted_origins=["https://kamilya-lms-dev.vercel.app"],
        cookie_profile="cross_site",
    )
    policy.enforce_request(
        _request(
            origin="https://kamilya-lms-dev.vercel.app",
            fetch_site="cross-site",
            content_type="application/json",
        )
    )


def test_refresh_cookie_wins_and_legacy_body_requires_explicit_nonproduction_opt_in() -> None:
    request = _request(cookie="kamilya_refresh=cookie-token")
    assert _policy(environment="test").read_refresh_token(request, "body-token") == "cookie-token"

    disabled = _policy(environment="test")
    with pytest.raises(HTTPException) as caught:
        disabled.read_refresh_token(_request(), "body-token")
    assert caught.value.detail["code"] == "legacy_refresh_body_forbidden"

    enabled = _policy(environment="test", allow_legacy_refresh_body=True)
    assert enabled.read_refresh_token(_request(), "body-token") == "body-token"


def test_hostile_origin_cannot_reach_login_credential_lookup(monkeypatch) -> None:
    authenticate = AsyncMock()
    monkeypatch.setattr(auth_router, "authenticate_user", authenticate)
    monkeypatch.setattr(
        auth_router,
        "get_browser_session_policy",
        lambda: _policy(environment="test"),
    )

    async def fake_db():
        yield SimpleNamespace()

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.example"},
            json={"email": "owner@example.kz", "password": "Password123!"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "browser_origin_forbidden"
    authenticate.assert_not_awaited()


def test_hostile_origin_cannot_rotate_or_revoke_refresh_session(monkeypatch) -> None:
    refresh_session = AsyncMock()
    blacklist = AsyncMock()
    decode = AsyncMock()
    monkeypatch.setattr(auth_router, "refresh_access_token", refresh_session)
    monkeypatch.setattr(auth_router, "blacklist_refresh_token", blacklist)
    monkeypatch.setattr(auth_router, "decode_token", decode)
    monkeypatch.setattr(auth_router, "get_browser_session_policy", lambda: _policy(environment="test"))

    async def fake_db():
        yield SimpleNamespace()

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    headers = {"Origin": "https://evil.example"}

    with TestClient(app) as client:
        client.cookies.set("kamilya_refresh", "opaque-refresh")
        refreshed = client.post("/api/v1/auth/refresh", headers=headers, json={})
        logged_out = client.post("/api/v1/auth/logout", headers=headers, json={})

    assert refreshed.status_code == 403
    assert logged_out.status_code == 403
    refresh_session.assert_not_awaited()
    blacklist.assert_not_awaited()
    decode.assert_not_awaited()


def test_hostile_origin_blocks_switch_role_before_current_user_lookup(monkeypatch) -> None:
    current_user_lookup = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(auth_router, "get_browser_session_policy", lambda: _policy(environment="test"))

    async def fake_db():
        yield SimpleNamespace()

    async def fake_current_user():
        return await current_user_lookup()

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[auth_router.get_current_user] = fake_current_user

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/switch-role",
            headers={"Origin": "https://evil.example"},
            json={"role": "admin"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "browser_origin_forbidden"
    current_user_lookup.assert_not_awaited()


def test_invalid_refresh_clears_cookie_on_the_actual_error_response(monkeypatch) -> None:
    monkeypatch.setattr(auth_router, "refresh_access_token", AsyncMock(side_effect=ValueError("invalid")))
    monkeypatch.setattr(auth_router, "get_browser_session_policy", lambda: _policy(environment="test"))

    async def fake_db():
        yield SimpleNamespace()

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db

    with TestClient(app) as client:
        client.cookies.set("kamilya_refresh", "invalid-refresh")
        response = client.post("/api/v1/auth/refresh", json={})

    assert response.status_code == 401
    cookie = response.headers["set-cookie"]
    assert "kamilya_refresh=" in cookie
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "SameSite=lax" in cookie


def test_hostile_origin_blocks_alternative_session_issuers_before_db_or_service(monkeypatch) -> None:
    db = AsyncMock()
    accept_invitation = AsyncMock()
    monkeypatch.setattr(invitations_router, "accept_invitation", accept_invitation)

    async def fake_db():
        yield db

    app = FastAPI()
    app.include_router(superadmin_router.router, prefix="/api/v1")
    app.include_router(invitations_router.router, prefix="/api/v1")
    app.include_router(tenant_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    headers = {"Origin": "https://evil.example"}

    with TestClient(app) as client:
        superadmin = client.post(
            "/api/v1/auth/superadmin-login",
            headers=headers,
            json={"email": "owner@example.kz", "password": "Password123!"},
        )
        invitation = client.post(
            "/api/v1/invitations/invite-token/accept",
            headers=headers,
            json={"code": "123456"},
        )
        tenant = client.post(
            "/api/v1/tenants/register",
            headers=headers,
            json={
                "company_name": "Kamilya Test",
                "contact_name": "Test Owner",
                "email": "owner@example.kz",
                "email_code": "123456",
                "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
                "privacy_consent_locale": "ru",
                "privacy_consent_surface": "tenant_registration",
                "terms_version": CURRENT_TERMS_VERSION,
            },
        )

    assert [superadmin.status_code, invitation.status_code, tenant.status_code] == [403, 403, 403]
    db.execute.assert_not_awaited()
    accept_invitation.assert_not_awaited()
