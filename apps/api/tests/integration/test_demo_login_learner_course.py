from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.demo.service import ensure_demo_student_course


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
async def test_demo_student_login_seeds_a_tenant_local_course_when_catalog_is_empty(
    client,
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
):
    from app.modules.auth import router as auth_router

    demo_slug = f"demo-empty-{uuid4().hex[:10]}"
    monkeypatch.setattr(auth_router, "DEMO_TENANT_SLUG", demo_slug)
    demo_tenant = await make_tenant(name="Empty Demo", slug=demo_slug, is_demo=True)

    other_tenant = await make_tenant(name="Other Tenant")
    other_methodologist = await make_user(other_tenant, role="methodologist")
    await make_course(
        other_tenant,
        other_methodologist,
        title="Cross-tenant Course",
        status="published",
        review_status="approved",
    )

    first_response = await client.post(
        "/api/v1/auth/demo-login",
        json={"role": "student"},
    )
    second_response = await client.post(
        "/api/v1/auth/demo-login",
        json={"role": "student"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    from app.models.courses import Course

    await set_current_tenant(demo_tenant)
    tenant_courses = (
        (
            await db_session.execute(
                select(Course).where(
                    Course.tenant_id == demo_tenant.id,
                    Course.status == "published",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(tenant_courses) == 1
    assert tenant_courses[0].title == "Знакомство с Kamilya"
    assert tenant_courses[0].source_analysis["demo_fixture"]["version"] == 1


@pytest.mark.asyncio
async def test_demo_course_fixture_is_never_created_for_a_regular_tenant(
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
):
    tenant = await make_tenant(name="Regular Tenant", is_demo=False)
    student = await make_user(tenant, role="student")
    await set_current_tenant(tenant)

    course_id = await ensure_demo_student_course(
        db_session,
        tenant_id=tenant.id,
        student_id=student.id,
    )

    assert course_id is None
