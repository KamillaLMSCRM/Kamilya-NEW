from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core.legal_versions import (
    CURRENT_PRIVACY_CONSENT_VERSION,
    CURRENT_PUBLIC_LEAD_CONSENT_VERSION,
    CURRENT_TERMS_VERSION,
)
from app.models.tenants import RegistrationLegalAcceptance, Tenant, TenantLead
from app.models.user_roles import UserRole
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
    monkeypatch.setattr(
        "app.modules.tenants.router.EmailService.delivery_ready",
        staticmethod(lambda: True),
    )
    registration_codes: dict[str, str] = {}

    async def capture_registration_code(_service, *, to_email, code):
        registration_codes[to_email] = code

    monkeypatch.setattr(
        "app.modules.tenants.router.EmailService.send_registration_code",
        capture_registration_code,
    )
    operator_notifications = []

    async def capture_operator_notification(_service, *, to_email, notification):
        operator_notifications.append((to_email, notification))

    monkeypatch.setattr(
        "app.modules.tenants.router.get_settings",
        lambda: SimpleNamespace(
            PUBLIC_LEAD_NOTIFICATION_EMAIL=(
                "askar@kml.kz,askar0007amirkhanov@gmail.com"
            )
        ),
    )
    monkeypatch.setattr(
        "app.modules.tenants.router.EmailService.send_public_lead_notification",
        capture_operator_notification,
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "app.modules.tenants.router.deliver_lead_outbox_task.apply_async",
        lambda *, args: dispatched.append(args[0]),
    )
    suffix = uuid4().hex[:12]
    email = f"qa-registration-{suffix}@example.com"

    code_response = await client.post(
        "/api/v1/tenants/register/request-code",
        json={"email": email},
    )
    assert code_response.status_code == 200
    assert code_response.json()["expires_in"] > 0
    assert email in registration_codes

    response = await client.post(
        "/api/v1/tenants/register",
        json={
            "company_name": f"QA Registration {suffix}",
            "contact_name": "Айдана QA",
            "email": email,
            "email_code": registration_codes[email],
            "password": "QA-registration-pass-2026!",
            "preferred_language": "ru",
            "intent": "try",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "kz_lms",
            "utm_content": "hero",
            "utm_term": "lms система",
            "referrer": "https://www.kml.kz/ru?utm_source=google",
            "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
            "privacy_consent_locale": "ru",
            "privacy_consent_surface": "forged-client-value",
            "terms_version": CURRENT_TERMS_VERSION,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "methodologist"
    assert payload["user"]["email"] == email
    assert payload["user"]["role"] == "methodologist"
    assert payload["user"]["roles"] == ["methodologist", "admin"]

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
    assert user.role == "methodologist"
    assert user.tenant_id == tenant.id
    assert tenant.is_financial_organization is False
    assigned_roles = set(
        (
            await db_session.execute(
                select(UserRole.role).where(UserRole.user_id == user.id)
            )
        ).scalars().all()
    )
    assert assigned_roles == {"admin", "methodologist"}

    trial_headers = {"Authorization": f"Bearer {payload['access_token']}"}
    catalog = await client.get("/api/v1/course-blueprints?locale=ru", headers=trial_headers)
    assert catalog.status_code == 200, catalog.text
    assert "kz-finance-information-security" not in {
        item["id"] for item in catalog.json()
    }
    first_course = await client.post(
        "/api/v1/courses",
        headers=trial_headers,
        json={"title": "QA trial first course", "description": "Trial workspace smoke"},
    )
    assert first_course.status_code == 201, first_course.text
    acceptance = (
        await db_session.execute(
            select(RegistrationLegalAcceptance).where(RegistrationLegalAcceptance.user_id == user.id)
        )
    ).scalar_one()
    assert acceptance.tenant_id == tenant.id
    assert acceptance.privacy_consent_version == CURRENT_PRIVACY_CONSENT_VERSION
    assert acceptance.privacy_consent_locale == "ru"
    assert acceptance.privacy_consent_surface == "tenant_registration"
    assert acceptance.terms_version == CURRENT_TERMS_VERSION
    assert acceptance.privacy_consent_at is not None
    assert acceptance.terms_accepted_at is not None
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
    assert [item[0] for item in operator_notifications] == [
        "askar@kml.kz",
        "askar0007amirkhanov@gmail.com",
    ]
    trial_notification = operator_notifications[0][1]
    assert trial_notification.lead_id == lead.id
    assert trial_notification.company == f"QA Registration {suffix}"
    assert trial_notification.email == email
    assert trial_notification.interest == "try"
    assert trial_notification.source_section == "tenant_registration"
    assert trial_notification.plan == "trial"
    assert trial_notification.utm_campaign == "kz_lms"
    await db_session.execute(
        text(
            "SELECT crm_finalize_lead_outbox("
            ":id, :token, 'defer', NULL, 'test_cleanup')"
        ),
        {"id": lead.id, "token": claimed["claim_token"]},
    )


@pytest.mark.asyncio
async def test_registration_rejects_unverified_email_without_creating_tenant(
    client,
    db_session,
    monkeypatch,
):
    suffix = uuid4().hex[:12]
    company_name = f"QA Unverified {suffix}"

    async def reject_unverified_email(**_kwargs):
        return None

    monkeypatch.setattr(
        "app.modules.tenants.router.consume_email_code",
        reject_unverified_email,
    )

    response = await client.post(
        "/api/v1/tenants/register",
        json={
            "company_name": company_name,
            "contact_name": "Айдана QA",
            "email": f"qa-unverified-{suffix}@example.com",
            "email_code": "000000",
            "password": "QA-registration-pass-2026!",
            "preferred_language": "ru",
            "intent": "try",
            "privacy_consent_version": CURRENT_PRIVACY_CONSENT_VERSION,
            "privacy_consent_locale": "ru",
            "privacy_consent_surface": "tenant_registration",
            "terms_version": CURRENT_TERMS_VERSION,
        },
    )

    assert response.status_code == 400
    assert response.json()["details"]["code"] == "invalid_registration_email_code"
    tenant = (
        await db_session.execute(select(Tenant).where(Tenant.name == company_name))
    ).scalar_one_or_none()
    assert tenant is None


@pytest.mark.asyncio
async def test_registration_legal_acceptance_rejects_cross_tenant_user(
    db_session,
    make_tenant,
    make_user,
):
    tenant_a = await make_tenant(name="QA Legal Acceptance A")
    tenant_b = await make_tenant(name="QA Legal Acceptance B")
    user_b = await make_user(tenant_b, email=f"qa-legal-{uuid4().hex[:12]}@example.com")
    await db_session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_a.id)})

    with pytest.raises(Exception, match="registration legal acceptance tenant ownership mismatch"):
        await db_session.execute(
            text(
                """
                INSERT INTO registration_legal_acceptances (
                    id, tenant_id, user_id, privacy_consent_version,
                    privacy_consent_locale, privacy_consent_surface, terms_version
                ) VALUES (
                    :id, :tenant_id, :user_id, :privacy_version,
                    'ru', 'tenant_registration', :terms_version
                )
                """
            ),
            {
                "id": uuid4(),
                "tenant_id": tenant_a.id,
                "user_id": user_b.id,
                "privacy_version": CURRENT_PRIVACY_CONSENT_VERSION,
                "terms_version": CURRENT_TERMS_VERSION,
            },
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
            "consent_version": CURRENT_PUBLIC_LEAD_CONSENT_VERSION,
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
    assert f'"consent_version": "{CURRENT_PUBLIC_LEAD_CONSENT_VERSION}"' in (lead.message or "")
    assert '"consented_at": "2026-08-07T16:01:00+00:00"' not in (lead.message or "")
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
    assert event["consent_version"] == CURRENT_PUBLIC_LEAD_CONSENT_VERSION
    assert event["consented_at"] != "2026-08-07T16:01:00+00:00"
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
