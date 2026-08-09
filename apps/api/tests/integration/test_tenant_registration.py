from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.models.tenants import Tenant, TenantLead
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
    dispatched: list[str] = []
    monkeypatch.setattr(
        "app.modules.tenants.router.deliver_lead_outbox_task.apply_async",
        lambda *, args: dispatched.append(args[0]),
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
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "kz_lms",
            "utm_content": "hero",
            "utm_term": "lms система",
            "referrer": "https://www.kml.kz/ru?utm_source=google",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "admin"
    assert payload["user"]["email"] == email

    tenant = (await db_session.execute(select(Tenant).where(Tenant.id == payload["tenant_id"]))).scalar_one()
    user = (await db_session.execute(select(User).where(User.id == payload["user_id"]))).scalar_one()
    assert tenant.status == "trial"
    assert tenant.settings["registration"]["attribution"] == {
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "kz_lms",
        "utm_content": "hero",
        "utm_term": "lms система",
        "referrer": "https://www.kml.kz/ru?utm_source=google",
    }
    assert user.role == "admin"
    assert user.tenant_id == tenant.id
    lead = (await db_session.execute(select(TenantLead).where(TenantLead.id == payload["lead_id"]))).scalar_one()
    assert "Landing attribution:" in (lead.message or "")
    assert '"utm_campaign": "kz_lms"' in (lead.message or "")
    claimed = (
        await db_session.execute(
            text("SELECT * FROM crm_claim_lead_outbox(:id)"),
            {"id": lead.id},
        )
    ).mappings().one()
    event = json.loads(bytes(claimed["payload_bytes"]))
    assert event["lead_id"] == str(lead.id)
    assert event["intent"] == "try"
    assert event["utm"]["campaign"] == "kz_lms"
    assert event["utm_campaign"] == "kz_lms"
    assert "billing_identifier" not in event
    assert dispatched == [str(lead.id)]
    await db_session.execute(
        text(
            "SELECT crm_finalize_lead_outbox("
            ":id, :token, 'defer', NULL, 'test_cleanup')"
        ),
        {"id": lead.id, "token": claimed["claim_token"]},
    )


@pytest.mark.asyncio
async def test_public_lead_keeps_landing_context_and_roi_attribution(
    client,
    db_session,
    monkeypatch,
):
    dispatched: list[str] = []

    def fail_broker_dispatch(*, args):
        dispatched.append(args[0])
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "app.modules.tenants.router.deliver_lead_outbox_task.apply_async",
        fail_broker_dispatch,
    )
    suffix = uuid4().hex[:12]
    response = await client.post(
        "/api/v1/public/leads",
        json={
            "name": "Айдана QA",
            "company": f"QA Landing {suffix}",
            "email": f"qa-landing-{suffix}@example.com",
            "companySize": 75,
            "industry": "finance",
            "interest": "roi_calc",
            "locale": "ru",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "kz_lms",
            "utm_content": "finance_hero",
            "utm_term": "проверка знаний сотрудников",
            "gclid": "test-gclid-123",
            "referrer": "https://www.kml.kz/ru?utm_source=google",
            "landing_page": "https://www.kml.kz/ru/finance?utm_source=google",
            "attribution_captured_at": "2026-08-07T16:00:00Z",
            "consent_version": "privacy-2026-08-07",
            "consented_at": "2026-08-07T16:01:00Z",
            "source_section": "roi",
            "plan": "corporate",
            "roi_employees": 75,
            "roi_industry": "finance",
            "roi_employee_band": "51-100",
            "roi_formula_version": "lead-assessment-v1",
        },
    )

    assert response.status_code == 201
    await db_session.execute(
        text("SELECT set_config('app.is_superadmin', 'true', true)")
    )
    lead = (await db_session.execute(select(TenantLead).where(TenantLead.id == response.json()["id"]))).scalar_one()
    assert lead.status == "lead_submitted"
    assert lead.source == "landing_form"
    assert lead.employee_count_range == "75"
    assert '"source_section": "roi"' in (lead.message or "")
    assert '"utm_content": "finance_hero"' in (lead.message or "")
    assert '"utm_term": "проверка знаний сотрудников"' in (lead.message or "")
    assert '"gclid": "test-gclid-123"' in (lead.message or "")
    assert '"consent_version": "privacy-2026-08-07"' in (lead.message or "")
    assert '"roi_employees": 75' in (lead.message or "")
    assert '"roi_formula_version": "lead-assessment-v1"' in (lead.message or "")
    claimed = (
        await db_session.execute(
            text("SELECT * FROM crm_claim_lead_outbox(:id)"),
            {"id": lead.id},
        )
    ).mappings().one()
    event = json.loads(bytes(claimed["payload_bytes"]))
    assert event["event_id"] == f"lmslead_{lead.id.hex}"
    assert event["lead_id"] == str(lead.id)
    assert event["intent"] == "demo"
    assert event["interest"] == "roi_calc"
    assert event["industry"] == "finance"
    assert event["utm"] == {
        "source": "google",
        "medium": "cpc",
        "campaign": "kz_lms",
        "content": "finance_hero",
        "term": "проверка знаний сотрудников",
    }
    assert event["utm_source"] == "google"
    assert event["utm_campaign"] == "kz_lms"
    assert event["utm_content"] == "finance_hero"
    assert event["consent_version"] == "privacy-2026-08-07"
    assert event["roi_employees"] == 75
    assert dispatched == [str(lead.id)]
    await db_session.execute(
        text(
            "SELECT crm_finalize_lead_outbox("
            ":id, :token, 'defer', NULL, 'test_cleanup')"
        ),
        {"id": lead.id, "token": claimed["claim_token"]},
    )


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


@pytest.mark.asyncio
async def test_password_login_ignores_inactive_duplicate_from_archived_tenant(
    client,
    make_tenant,
    make_user,
):
    email = f"qa-reused-email-{uuid4().hex[:12]}@example.com"
    password = "QA-Active-Login-2026!"
    active_tenant = await make_tenant(name="QA Active Tenant")
    active_user = await make_user(
        active_tenant,
        role="admin",
        email=email,
        password=password,
    )
    archived_tenant = await make_tenant(
        name="QA Archived Tenant",
        status="archived",
    )
    await make_user(
        archived_tenant,
        role="admin",
        email=email,
        is_active=False,
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 200
    assert response.json()["user"]["user_id"] == str(active_user.id)
