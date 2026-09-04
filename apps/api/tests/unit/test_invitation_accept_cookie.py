from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.modules.users import invitations_router


def test_accept_invitation_sets_same_site_http_only_refresh_cookie(monkeypatch):
    async def fake_accept_invitation(*_args, **_kwargs):
        user_id = uuid4()
        tenant_id = uuid4()
        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "role": "student",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "user": {
                "id": str(user_id),
                "tenant_id": str(tenant_id),
                "role": "student",
                "roles": ["student"],
                "full_name": "Test Learner",
                "email": "learner@example.kz",
            },
            "next_url": f"/courses/{uuid4()}",
        }

    async def fake_db():
        yield object()

    monkeypatch.setattr(
        invitations_router,
        "accept_invitation",
        fake_accept_invitation,
    )

    app = FastAPI()
    app.include_router(invitations_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/invitations/invite-token/accept",
            json={"code": "123456"},
        )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "kamilya_refresh=refresh-token" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Partitioned" not in cookie
    assert "Path=/api/v1/auth" in cookie
