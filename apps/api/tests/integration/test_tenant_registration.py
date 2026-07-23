from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.tenants import Tenant
from app.models.users import User


@pytest.mark.asyncio
async def test_registration_succeeds_when_trial_email_provider_fails(
    client,
    db_session,
    monkeypatch,
):
    async def fail_email(*_args, **_kwargs):
        raise RuntimeError("notification provider unavailable")

    monkeypatch.setattr(
        "app.modules.tenants.router.EmailService.send_trial_started",
        fail_email,
    )
    suffix = uuid4().hex[:12]
    email = f"qa-registration-{suffix}@example.com"

    response = await client.post(
        "/api/v1/tenants/register",
        json={
            "company_name": f"QA Registration {suffix}",
            "contact_name": "Айдана QA",
            "email": email,
            "password": "QA-registration-pass-2026!",
            "preferred_language": "ru",
            "intent": "try",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "admin"
    assert payload["user"]["email"] == email

    tenant = (
        await db_session.execute(
            select(Tenant).where(Tenant.id == payload["tenant_id"])
        )
    ).scalar_one()
    user = (
        await db_session.execute(
            select(User).where(User.id == payload["user_id"])
        )
    ).scalar_one()
    assert tenant.status == "trial"
    assert user.role == "admin"
    assert user.tenant_id == tenant.id


@pytest.mark.asyncio
async def test_password_login_returns_frontend_user_payload(
    client,
    make_tenant,
    make_user,
):
    tenant = await make_tenant(name="QA Password Login")
    user = await make_user(
        tenant,
        role="methodologist",
        email=f"qa-methodologist-{uuid4().hex[:12]}@example.com",
        first_name="Мадина",
        last_name="QA",
        password="QA-Methodologist-2026!",
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "QA-Methodologist-2026!",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["user_id"] == str(user.id)
    assert payload["user"]["tenant_id"] == str(tenant.id)
    assert payload["user"]["role"] == "methodologist"
    assert payload["user"]["full_name"] == "Мадина QA"
