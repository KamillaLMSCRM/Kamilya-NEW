from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.models.enrollment import Enrollment

pytestmark = pytest.mark.asyncio


async def test_audience_advisor_is_methodologist_only_and_has_no_assignment_write(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Audience Tenant")
    methodologist = await make_user(tenant, role="methodologist")
    admin = await make_user(tenant, role="admin")
    course = await make_course(tenant, methodologist, title="Information security", status="draft")

    before = await db_session.scalar(select(func.count(Enrollment.id)))
    with patch(
        "app.modules.ai.router.ResilientLLMClient.from_settings_async",
        new=AsyncMock(return_value=None),
    ):
        response = await client.post(
            "/api/v1/ai/chat",
            headers=auth_headers(methodologist),
            json={
                "course_id": str(course.id),
                "context": "course",
                "message": "Кому подходит этот курс?",
                "intent": "audience_recommendation",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audience_recommendation"]["assignment_url"] is None
    assert "draft" not in body["reply"]
    after = await db_session.scalar(select(func.count(Enrollment.id)))
    assert after == before

    admin_response = await client.post(
        "/api/v1/ai/chat",
        headers=auth_headers(admin),
        json={
            "course_id": str(course.id),
            "message": "Кому подходит этот курс?",
            "intent": "audience_recommendation",
        },
    )
    assert admin_response.status_code == 403


async def test_audience_advisor_hides_course_across_tenants(
    client, make_tenant, make_user, make_course, auth_headers
):
    tenant_a = await make_tenant(name="Tenant A")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    course_a = await make_course(tenant_a, methodologist_a, title="Private course")
    tenant_b = await make_tenant(name="Tenant B")
    methodologist_b = await make_user(tenant_b, role="methodologist")

    response = await client.post(
        "/api/v1/ai/chat",
        headers=auth_headers(methodologist_b),
        json={
            "course_id": str(course_a.id),
            "message": "Кому подходит этот курс?",
            "intent": "audience_recommendation",
        },
    )
    assert response.status_code == 404


async def test_published_course_gets_navigation_only_not_assignment_command(
    client, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Published Audience Tenant")
    methodologist = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, methodologist, title="Published course", status="published")

    with patch(
        "app.modules.ai.router.ResilientLLMClient.from_settings_async",
        new=AsyncMock(return_value=None),
    ):
        response = await client.post(
            "/api/v1/ai/chat",
            headers=auth_headers(methodologist),
            json={
                "course_id": str(course.id),
                "message": "Кому подходит этот курс?",
                "intent": "audience_recommendation",
            },
        )

    assert response.status_code == 200, response.text
    recommendation = response.json()["audience_recommendation"]
    assert recommendation["assignment_url"] == f"/assignments?course_id={course.id}"
    assert "POST" not in response.json()["reply"]
    assert "Enrollment" not in response.json()["reply"]
