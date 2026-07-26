"""Database-backed contract tests for organization-wide training rules."""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.enrollment import Enrollment
from app.modules.positions.assignment_service import recompute_enrollments
from app.modules.training_rules.models import OrganizationCourseRule


async def test_organization_rule_applies_to_existing_and_new_employee(
    client,
    db_session,
    auth_headers,
    make_course,
    make_tenant,
    make_user,
):
    tenant = await make_tenant(name="Organization rules tenant")
    methodologist = await make_user(tenant, role="methodologist")
    existing_employee = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, status="published")

    attach = await client.post(
        "/api/v1/training-rules/organization",
        headers=auth_headers(methodologist),
        json={"course_id": str(course.id), "required": True},
    )
    assert attach.status_code == 201, attach.text

    existing = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.tenant_id == tenant.id,
            Enrollment.user_id == existing_employee.id,
            Enrollment.course_id == course.id,
        )
    )
    assert existing is not None
    assert existing.source == "organization"
    methodologist_enrollment = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.tenant_id == tenant.id,
            Enrollment.user_id == methodologist.id,
            Enrollment.course_id == course.id,
        )
    )
    assert methodologist_enrollment is None

    new_employee = await make_user(tenant, role="student")
    await recompute_enrollments(db_session, new_employee.id)
    inherited = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.tenant_id == tenant.id,
            Enrollment.user_id == new_employee.id,
            Enrollment.course_id == course.id,
        )
    )
    assert inherited is not None
    assert inherited.source == "organization"


async def test_detach_removes_in_progress_but_keeps_completed_organization_enrollment(
    client,
    db_session,
    auth_headers,
    make_course,
    make_tenant,
    make_user,
):
    tenant = await make_tenant(name="Organization rule detach tenant")
    methodologist = await make_user(tenant, role="methodologist")
    completed_employee = await make_user(tenant, role="student")
    in_progress_employee = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, status="published")

    attach = await client.post(
        "/api/v1/training-rules/organization",
        headers=auth_headers(methodologist),
        json={"course_id": str(course.id)},
    )
    assert attach.status_code == 201, attach.text
    completed = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.user_id == completed_employee.id,
            Enrollment.course_id == course.id,
        )
    )
    completed.status = "completed"
    await db_session.flush()

    detach = await client.delete(
        f"/api/v1/training-rules/organization/{course.id}",
        headers=auth_headers(methodologist),
    )
    assert detach.status_code == 200, detach.text

    completed_after = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.user_id == completed_employee.id,
            Enrollment.course_id == course.id,
        )
    )
    removed_after = await db_session.scalar(
        select(Enrollment).where(
            Enrollment.user_id == in_progress_employee.id,
            Enrollment.course_id == course.id,
        )
    )
    assert completed_after is not None
    assert removed_after is None


@pytest.mark.parametrize("role", ["admin", "student"])
async def test_organization_rule_mutation_denies_non_methodologist(
    client,
    auth_headers,
    make_course,
    make_tenant,
    make_user,
    role,
):
    tenant = await make_tenant(name=f"Denied {role}")
    methodologist = await make_user(tenant, role="methodologist")
    caller = await make_user(tenant, role=role)
    course = await make_course(tenant, methodologist, status="published")

    response = await client.post(
        "/api/v1/training-rules/organization",
        headers=auth_headers(caller),
        json={"course_id": str(course.id)},
    )
    assert response.status_code == 403


async def test_organization_rule_rejects_foreign_course_and_department_list_denies_admin(
    client,
    auth_headers,
    make_course,
    make_tenant,
    make_user,
):
    tenant_a = await make_tenant(name="Rule tenant A")
    tenant_b = await make_tenant(name="Rule tenant B")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    methodologist_b = await make_user(tenant_b, role="methodologist")
    admin_b = await make_user(tenant_b, role="admin")
    foreign_course = await make_course(tenant_a, methodologist_a, status="published")

    foreign = await client.post(
        "/api/v1/training-rules/organization",
        headers=auth_headers(methodologist_b),
        json={"course_id": str(foreign_course.id)},
    )
    assert foreign.status_code == 404

    opaque = await client.post(
        "/api/v1/training-rules/organization",
        headers=auth_headers(methodologist_b),
        json={"course_id": str(uuid4())},
    )
    assert opaque.status_code == 404

    department_read = await client.get("/api/v1/departments", headers=auth_headers(admin_b))
    assert department_read.status_code == 403


async def test_database_rejects_cross_tenant_rule_author(
    db_session,
    make_course,
    make_tenant,
    make_user,
):
    tenant_a = await make_tenant(name="Rule author tenant A")
    tenant_b = await make_tenant(name="Rule author tenant B")
    author_a = await make_user(tenant_a, role="methodologist")
    foreign_author = await make_user(tenant_b, role="methodologist")
    course = await make_course(tenant_a, author_a, status="published")

    db_session.add(
        OrganizationCourseRule(
            tenant_id=tenant_a.id,
            course_id=course.id,
            created_by=foreign_author.id,
        )
    )

    with pytest.raises(DBAPIError, match="author must belong to the same tenant"):
        await db_session.flush()
