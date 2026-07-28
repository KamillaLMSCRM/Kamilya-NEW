import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortMember
from app.modules.positions.models import DepartmentCourse, Position, PositionCourse
from app.modules.training_rules.models import OrganizationCourseRule

pytestmark = pytest.mark.asyncio


async def test_audience_advisor_is_methodologist_only_and_has_no_assignment_write(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Audience Tenant")
    methodologist = await make_user(tenant, role="methodologist")
    admin = await make_user(tenant, role="admin")
    course = await make_course(tenant, methodologist, title="Information security", status="draft")

    tracked_models = (Enrollment, OrganizationCourseRule, PositionCourse, DepartmentCourse, Cohort, CohortMember, User)
    async def table_counts():
        return {
            model.__tablename__: await db_session.scalar(select(func.count()).select_from(model))
            for model in tracked_models
        }

    before = await table_counts()
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
    after = await table_counts()
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


async def test_typed_audience_question_uses_structure_without_explicit_intent(
    client, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Typed Audience Tenant")
    methodologist = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, methodologist, title="Information security")

    with patch(
        "app.modules.ai.router.ResilientLLMClient.from_settings_async",
        new=AsyncMock(return_value=None),
    ):
        response = await client.post(
            "/api/v1/ai/chat",
            headers=auth_headers(methodologist),
            json={
                "course_id": str(course.id),
                "message": "Кому его назначить? Посмотри по моей структуре",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["audience_recommendation"] is not None


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


async def test_unlinked_course_exposes_bounded_real_structure_and_discards_unknown_ref(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    auth_headers,
):
    tenant = await make_tenant(name="Bounded Audience Tenant")
    methodologist = await make_user(tenant, role="methodologist")
    student = await make_user(tenant, role="student", email="learner@example.test")
    department = Department(
        id=uuid4(), tenant_id=tenant.id, name="Operations", slug="operations", description="Customer operations",
    )
    position = Position(
        id=uuid4(), tenant_id=tenant.id, name="Operations specialist", department="Operations",
        department_id=department.id, responsibilities="Handle contact alice@example.com +7 777 123 45 67 @private_handle",
        requirements="Follow the operating procedure", level="specialist",
    )
    cohort = Cohort(id=uuid4(), tenant_id=tenant.id, name="New operations hires", description="New hire onboarding group")
    db_session.add_all([department, position, cohort])
    await db_session.flush()
    student.position_id = position.id
    db_session.add(CohortMember(id=uuid4(), tenant_id=tenant.id, cohort_id=cohort.id, user_id=student.id))
    course = await make_course(tenant, methodologist, title="Operations safety", description="Contact owner@example.com for access")
    module = await make_module(course, title="Safe operations")
    await make_lesson(module, title="Contact handling", content="Call +7 700 111 22 33 or message @lesson_handle")
    await db_session.flush()

    class CapturingLLM:
        prompt = ""

        async def ainvoke(self, messages):
            self.prompt = messages[-1]["content"]
            return SimpleNamespace(content=json.dumps({
                "selected_refs": ["position_1", "unknown_ref"],
                "primary_refs": ["position_1"],
                "secondary_refs": [],
            }))

    llm = CapturingLLM()
    with patch(
        "app.modules.ai.router.ResilientLLMClient.from_settings_async",
        new=AsyncMock(return_value=llm),
    ):
        response = await client.post(
            "/api/v1/ai/chat",
            headers=auth_headers(methodologist),
            json={
                "course_id": str(course.id),
                "message": "Кому подходит этот курс?",
                "language": "en",
                "intent": "audience_recommendation",
            },
        )

    assert response.status_code == 200, response.text
    scopes = response.json()["audience_recommendation"]["recommended_scopes"]
    assert any(scope["type"] == "position" and scope["name"] == "Operations specialist" for scope in scopes)
    assert "unknown_ref" not in {scope["id"] for scope in scopes}
    assert "alice@example.com" not in llm.prompt
    assert "+7 777 123 45 67" not in llm.prompt
    assert "@private_handle" not in llm.prompt
    assert "Contact handling" in llm.prompt
    assert len(llm.prompt) <= 18_400
