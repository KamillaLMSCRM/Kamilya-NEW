from datetime import UTC, datetime

from app.models.enrollment import Enrollment
from app.modules.positions.models import Position, PositionCourse


async def test_staff_structure_deduplicates_rules_and_materialized_enrollments(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    auth_headers,
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    employee = await make_user(tenant, role="student")
    course = await make_course(
        tenant,
        methodologist,
        title="Required course",
        status="published",
    )
    position = Position(
        tenant_id=tenant.id,
        name="Operator",
        department="Operations",
        level="",
        responsibilities="",
        requirements="",
        employee_count=1,
    )
    db_session.add(position)
    await db_session.flush()
    employee.position_id = position.id
    db_session.add(
        PositionCourse(
            tenant_id=tenant.id,
            position_id=position.id,
            course_id=course.id,
            required=True,
        )
    )
    db_session.add(
        Enrollment(
            tenant_id=tenant.id,
            user_id=employee.id,
            course_id=course.id,
            source="position",
            status="completed",
            completed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/admin/staff/structure",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 200
    payload = response.json()
    employee_payload = payload["departments"][0]["positions"][0]["employees"][0]
    assert employee_payload["assigned_courses"] == 1
    assert employee_payload["completed_courses"] == 1
    assert employee_payload["ready_percent"] == 100
    assert payload["summary"]["total_assigned_courses"] == 1
    assert payload["summary"]["overall_ready_percent"] == 100
