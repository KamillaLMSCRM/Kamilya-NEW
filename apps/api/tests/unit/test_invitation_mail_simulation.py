"""Local mail-simulated public invitation journey.

The database, Redis, audit, and refresh-session boundaries are deliberately
isolated here.  The request-code and accept endpoints and the invitation OTP
implementation remain real; the code is obtained only from the captured
synthetic email transport.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.email import EmailService
from app.modules.auth import email_otp
from app.modules.users import invitations_router


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return []


class _MailDB:
    """Small async DB boundary sufficient for the public invitation service."""

    def __init__(self, invitation, user, tenant):
        self.invitation = invitation
        self.user = user
        self.tenant = tenant
        self.commits = 0
        self.statements = []

    async def execute(self, statement, *_args, **_kwargs):
        rendered = str(statement)
        self.statements.append(rendered)
        if "user_invitations" in rendered:
            return _Result(self.invitation)
        if "tenants" in rendered:
            return _Result(self.tenant)
        return _Result(None)

    async def get(self, _model, _identity):
        return self.user

    async def commit(self):
        self.commits += 1


def _journey():
    tenant_id = uuid4()
    user_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="learner@example.kz",
        first_name="Aizhan",
        last_name="Akhmetova",
        personnel_number="EMP-007",
        role="student",
        token="public-invitation-token",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        user_id=user_id,
        accepted_at=None,
        verification_method=None,
        accepted_ip=None,
        accepted_user_agent=None,
    )
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        email=invitation.email,
        first_name=invitation.first_name,
        last_name=invitation.last_name,
        personnel_number=invitation.personnel_number,
        password_hash=None,
        position_id=None,
        is_active=False,
        status="pending",
        email_verified_at=None,
        last_login=None,
    )
    return invitation, user, SimpleNamespace(id=tenant_id, name="Acme HR")


def _app(db):
    async def fake_db():
        yield db

    app = FastAPI()
    app.include_router(invitations_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    return app


@pytest.fixture(autouse=True)
def _reset_otp(monkeypatch):
    email_otp._memory_store.clear()
    monkeypatch.setattr(email_otp, "_get_redis", _async_value(None))
    monkeypatch.setattr(EmailService, "delivery_ready", staticmethod(lambda: True))
    yield
    email_otp._memory_store.clear()


@pytest.mark.asyncio
async def test_public_invitation_request_mail_accept_and_replay(monkeypatch):
    invitation, user, tenant = _journey()
    db = _MailDB(invitation, user, tenant)
    original_identity = {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "personnel_number": user.personnel_number,
        "password_hash": user.password_hash,
    }
    sent = []

    async def capture_send(_self, **message):
        sent.append(message)

    monkeypatch.setattr(EmailService, "_send", capture_send)
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: 246801)
    monkeypatch.setattr(
        "app.modules.auth.service.build_user_payload",
        _async_value(
            {
                "id": str(user.id),
                "tenant_id": str(user.tenant_id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "personnel_number": user.personnel_number,
                "role": "student",
                "roles": ["student"],
                "is_active": True,
            }
        ),
    )
    monkeypatch.setattr("app.modules.auth.service.issue_refresh_session", _async_value(None))
    monkeypatch.setattr("app.modules.audit.service.log_action", _async_value(None))

    with TestClient(_app(db)) as client:
        requested = client.post(
            f"/api/v1/invitations/{invitation.token}/request-code"
        )
        assert requested.status_code == 200
        assert len(sent) == 1
        assert sent[0]["to_email"] == invitation.email
        mail_code = re.search(r"\b(\d{6})\b", sent[0]["text"]).group(1)
        repeated_request = client.post(
            f"/api/v1/invitations/{invitation.token}/request-code"
        )
        assert repeated_request.status_code == 200
        assert len(sent) == 1

        missing = client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={},
        )
        assert missing.status_code == 422

        malformed = client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={"code": "123"},
        )
        assert malformed.status_code == 422

        assert client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={"code": "000000"},
        ).status_code == 401
        assert db.commits == 0
        assert user.is_active is False
        assert invitation.status == "pending"

        accepted = client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={"code": mail_code},
            headers={"user-agent": "mail-sim-test"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["user"]["personnel_number"] == "EMP-007"
        assert accepted.json()["user"]["id"] == str(original_identity["id"])
        assert accepted.json()["user"]["tenant_id"] == str(original_identity["tenant_id"])
        assert "refresh_token" not in accepted.json()
        cookie = accepted.headers["set-cookie"]
        assert "kamilya_refresh=" in cookie
        assert "HttpOnly" in cookie and "Secure" in cookie
        assert user.is_active is True
        assert user.status == "active"
        assert user.id == original_identity["id"]
        assert user.tenant_id == original_identity["tenant_id"]
        assert user.email == original_identity["email"]
        assert user.first_name == original_identity["first_name"]
        assert user.last_name == original_identity["last_name"]
        assert user.personnel_number == original_identity["personnel_number"]
        assert user.password_hash == original_identity["password_hash"]
        assert invitation.status == "accepted"
        assert invitation.verification_method == "email_otp"
        assert db.commits == 1

        replay = client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={"code": mail_code},
        )
        assert replay.status_code == 410
        assert db.commits == 1


def _async_value(value):
    async def resolve(*_args, **_kwargs):
        return value

    return resolve


def test_scoped_login_code_cannot_accept_invitation(monkeypatch):
    invitation, user, tenant = _journey()
    db = _MailDB(invitation, user, tenant)
    sent = []

    async def capture_send(_self, **message):
        sent.append(message)

    monkeypatch.setattr(EmailService, "_send", capture_send)
    values = iter((111111, 222222))
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: next(values))

    async def scenario():
        await email_otp.create_email_code(
            email=user.email,
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
            role="student",
        )

    import asyncio

    asyncio.run(scenario())
    with TestClient(_app(db)) as client:
        assert client.post(
            f"/api/v1/invitations/{invitation.token}/request-code"
        ).status_code == 200
        assert re.search(r"\b322222\b", sent[0]["text"])
        response = client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={"code": "211111"},
        )
    assert response.status_code == 401
    assert invitation.status == "pending"
    assert user.is_active is False


def test_delivery_failure_invalidates_mail_code(monkeypatch):
    invitation, user, tenant = _journey()
    db = _MailDB(invitation, user, tenant)

    sent = []

    async def fail_send(_self, **message):
        sent.append(message)
        raise RuntimeError("simulated local transport failure")

    monkeypatch.setattr(EmailService, "_send", fail_send)
    monkeypatch.setattr(email_otp.secrets, "randbelow", lambda _limit: 246801)

    with TestClient(_app(db)) as client:
        failed = client.post(
            f"/api/v1/invitations/{invitation.token}/request-code"
        )
        assert failed.status_code == 503
        assert len(sent) == 1
        mail_code = re.search(r"\b(\d{6})\b", sent[0]["text"]).group(1)
        rejected = client.post(
            f"/api/v1/invitations/{invitation.token}/accept",
            json={"code": mail_code},
        )
    assert rejected.status_code == 401
    assert db.commits == 0
    assert invitation.status == "pending"
    assert user.is_active is False
