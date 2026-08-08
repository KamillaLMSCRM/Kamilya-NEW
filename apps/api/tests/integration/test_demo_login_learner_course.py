from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models.enrollment import Enrollment
from app.models.users import User


@pytest.mark.asyncio
async def test_demo_student_login_exposes_an_assigned_published_course(
    client,
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
):
    from app.modules.auth import router as auth_router

    demo_slug = f"demo-contract-{uuid4().hex[:10]}"
    monkeypatch.setattr(auth_router, "DEMO_TENANT_SLUG", demo_slug)

    tenant = await make_tenant(
        name="Demo Contract Tenant",
        slug=demo_slug,
        is_demo=True,
    )
    methodologist = await make_user(tenant, role="methodologist")
    course = await make_course(
        tenant,
        methodologist,
        title="Demo Contract Course",
        status="published",
        review_status="approved",
    )
    module = await make_module(course, title="Demo Module")
    await make_lesson(module, title="Demo Lesson")

    login_response = await client.post(
        "/api/v1/auth/demo-login",
        json={"role": "student"},
    )
    assert login_response.status_code == 200

    token = login_response.json()["access_token"]
    dashboard_response = await client.get(
        "/api/v1/student/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert dashboard_response.status_code == 200
    enrolled_courses = dashboard_response.json()["enrolled_courses"]
    assert [item["course_id"] for item in enrolled_courses] == [str(course.id)]

    second_login_response = await client.post(
        "/api/v1/auth/demo-login",
        json={"role": "student"},
    )
    assert second_login_response.status_code == 200

    await db_session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant.id)},
    )
    demo_student_id = await db_session.scalar(
        select(User.id).where(
            User.tenant_id == tenant.id,
            User.email == "student@demo.kml",
        )
    )
    enrollment_count = await db_session.scalar(
        select(func.count(Enrollment.id)).where(
            Enrollment.tenant_id == tenant.id,
            Enrollment.user_id == demo_student_id,
            Enrollment.course_id == course.id,
        )
    )
    assert enrollment_count == 1


@pytest.mark.asyncio
async def test_demo_student_login_fails_closed_without_tenant_course(
    client,
    monkeypatch,
    make_tenant,
    make_user,
    make_course,
):
    from app.modules.auth import router as auth_router

    demo_slug = f"demo-empty-{uuid4().hex[:10]}"
    monkeypatch.setattr(auth_router, "DEMO_TENANT_SLUG", demo_slug)
    await make_tenant(name="Empty Demo", slug=demo_slug, is_demo=True)

    other_tenant = await make_tenant(name="Other Tenant")
    other_methodologist = await make_user(other_tenant, role="methodologist")
    await make_course(
        other_tenant,
        other_methodologist,
        title="Cross-tenant Course",
        status="published",
        review_status="approved",
    )

    response = await client.post(
        "/api/v1/auth/demo-login",
        json={"role": "student"},
    )

    assert response.status_code == 503
    assert response.json()["message"] == "Demo course is temporarily unavailable"
