from uuid import UUID

from app.core.email import EmailService
from app.modules.support.models import SupportRequest


async def test_create_support_request_persists_authenticated_context_and_sends_email(
    client,
    db_session,
    make_tenant,
    make_user,
    auth_headers,
    monkeypatch,
):
    tenant = await make_tenant(name="Support Tenant")
    user = await make_user(
        tenant,
        role="student",
        email="learner@example.kz",
        first_name="Learner",
        last_name="One",
    )
    captured = {}

    async def fake_send_support_request(_service, **kwargs):
        captured.update(kwargs)
        return "provider-message-id"

    monkeypatch.setattr(EmailService, "send_support_request", fake_send_support_request)

    response = await client.post(
        "/api/v1/support/requests",
        headers=auth_headers(user),
        json={
            "category": "technical",
            "subject": "  Course page does not open  ",
            "message": "  The assigned course returns an error after I press Open.  ",
            "current_path": "/assignments?course=example",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["reference"].startswith("KML-")
    assert body["delivery_status"] == "sent"

    item = await db_session.get(SupportRequest, UUID(body["id"]))
    assert item is not None
    assert item.tenant_id == tenant.id
    assert item.created_by == user.id
    assert item.requester_email == "learner@example.kz"
    assert item.subject == "Course page does not open"
    assert item.delivery_status == "sent"
    assert captured["to_email"] == "support@kml.kz"
    assert captured["reply_to"] == "learner@example.kz"
    assert captured["tenant_name"] == "Support Tenant"


async def test_support_request_rejects_platform_superadmin(
    client,
    make_superadmin,
    auth_headers,
):
    user = await make_superadmin()
    response = await client.post(
        "/api/v1/support/requests",
        headers=auth_headers(user),
        json={
            "category": "other",
            "subject": "Platform request",
            "message": "This request has no tenant context.",
        },
    )

    assert response.status_code == 403


async def test_support_request_validates_trimmed_message_length(
    client,
    make_tenant,
    make_user,
    auth_headers,
):
    tenant = await make_tenant()
    user = await make_user(tenant)
    response = await client.post(
        "/api/v1/support/requests",
        headers=auth_headers(user),
        json={
            "category": "technical",
            "subject": "Valid subject",
            "message": "          x          ",
        },
    )

    assert response.status_code == 422
