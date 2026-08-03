"""Database-backed learning-program lifecycle coverage."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.enrollment import Enrollment
from app.modules.learning_paths.models import LearningPath, LearningPathAssignment


async def test_learning_program_assignment_and_linear_release(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
):
    tenant = await make_tenant(name="Programs tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    unassigned_learner = await make_user(tenant, role="student")
    first = await make_course(
        tenant,
        methodologist,
        title="Welcome",
        status="published",
    )
    second = await make_course(
        tenant,
        methodologist,
        title="Security",
        status="published",
    )

    create_response = await client.post(
        "/api/v1/learning-paths",
        headers=auth_headers(methodologist),
        json={
            "title": "New employee onboarding",
            "description": "Required first-week program",
            "sequencing_mode": "linear",
        },
    )
    assert create_response.status_code == 201, create_response.text
    draft = create_response.json()
    assert draft["status"] == "draft"
    assert draft["version"] == 1

    optional_only_response = await client.put(
        f"/api/v1/learning-paths/{draft['id']}/curriculum",
        headers=auth_headers(methodologist),
        json={"steps": [{"course_id": str(first.id), "required": False}]},
    )
    assert optional_only_response.status_code == 200
    optional_publish_response = await client.post(
        f"/api/v1/learning-paths/{draft['id']}/publish",
        headers=auth_headers(methodologist),
    )
    assert optional_publish_response.status_code == 422
    assert (
        optional_publish_response.json()["details"]["code"]
        == "required_curriculum_step_required"
    )

    curriculum_response = await client.put(
        f"/api/v1/learning-paths/{draft['id']}/curriculum",
        headers=auth_headers(methodologist),
        json={
            "steps": [
                {"course_id": str(first.id), "required": True},
                {"course_id": str(second.id), "required": True},
            ]
        },
    )
    assert curriculum_response.status_code == 200, curriculum_response.text
    assert [item["course_id"] for item in curriculum_response.json()["courses"]] == [
        str(first.id),
        str(second.id),
    ]

    publish_response = await client.post(
        f"/api/v1/learning-paths/{draft['id']}/publish",
        headers=auth_headers(methodologist),
    )
    assert publish_response.status_code == 200, publish_response.text
    assert publish_response.json()["status"] == "published"

    immutable_response = await client.patch(
        f"/api/v1/learning-paths/{draft['id']}",
        headers=auth_headers(methodologist),
        json={"title": "Silent mutation"},
    )
    assert immutable_response.status_code == 409
    assert immutable_response.json()["details"]["code"] == "published_version_immutable"

    unassigned_response = await client.get(
        "/api/v1/learning-paths/my",
        headers=auth_headers(unassigned_learner),
    )
    assert unassigned_response.status_code == 200
    assert unassigned_response.json() == []

    assignment_response = await client.post(
        f"/api/v1/learning-paths/{draft['id']}/assignments",
        headers=auth_headers(methodologist),
        json={
            "user_ids": [str(learner.id)],
            "cohort_ids": [],
            "department_ids": [],
            "position_ids": [],
        },
    )
    assert assignment_response.status_code == 201, assignment_response.text
    assert assignment_response.json()["added"] == 1

    learner_response = await client.get(
        "/api/v1/learning-paths/my",
        headers=auth_headers(learner),
    )
    assert learner_response.status_code == 200, learner_response.text
    programs = learner_response.json()
    assert len(programs) == 1
    assert programs[0]["current_course_id"] == str(first.id)
    assert [step["state"] for step in programs[0]["steps"]] == [
        "available",
        "locked",
    ]

    enrollment_rows = (
        await db_session.execute(
            select(Enrollment).where(
                Enrollment.tenant_id == tenant.id,
                Enrollment.user_id == learner.id,
            )
        )
    ).scalars().all()
    assert [(row.course_id, row.source) for row in enrollment_rows] == [
        (first.id, "learning_path")
    ]

    enrollment_rows[0].status = "completed"
    await db_session.flush()

    released_response = await client.get(
        "/api/v1/learning-paths/my",
        headers=auth_headers(learner),
    )
    assert released_response.status_code == 200, released_response.text
    released_program = released_response.json()[0]
    assert released_program["current_course_id"] == str(second.id)
    assert [step["state"] for step in released_program["steps"]] == [
        "completed",
        "available",
    ]

    released_course_ids = set(
        (
            await db_session.execute(
                select(Enrollment.course_id).where(
                    Enrollment.tenant_id == tenant.id,
                    Enrollment.user_id == learner.id,
                )
            )
        ).scalars().all()
    )
    assert released_course_ids == {first.id, second.id}

    version_response = await client.post(
        f"/api/v1/learning-paths/{draft['id']}/versions",
        headers=auth_headers(methodologist),
    )
    assert version_response.status_code == 201, version_response.text
    new_version = version_response.json()
    assert new_version["status"] == "draft"
    assert new_version["family_id"] == draft["family_id"]
    assert new_version["version"] == 2
    assert [item["course_id"] for item in new_version["courses"]] == [
        str(first.id),
        str(second.id),
    ]

    assignment_list_response = await client.get(
        f"/api/v1/learning-paths/{draft['id']}/assignments",
        headers=auth_headers(methodologist),
    )
    assert assignment_list_response.status_code == 200
    assignment_item = assignment_list_response.json()[0]
    assert assignment_item["user_name"] == f"{learner.first_name} {learner.last_name}"
    assert assignment_item["user_email"] == learner.email

    cancel_response = await client.post(
        f"/api/v1/learning-paths/assignments/{assignment_item['id']}/cancel",
        headers=auth_headers(methodologist),
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    assignment_history_response = await client.get(
        f"/api/v1/learning-paths/{draft['id']}/assignments",
        headers=auth_headers(methodologist),
    )
    assert assignment_history_response.status_code == 200
    assert assignment_history_response.json()[0]["status"] == "cancelled"

    cancelled_learner_response = await client.get(
        "/api/v1/learning-paths/my",
        headers=auth_headers(learner),
    )
    assert cancelled_learner_response.status_code == 200
    assert cancelled_learner_response.json() == []


async def test_learning_program_is_tenant_scoped(
    client,
    auth_headers,
    make_tenant,
    make_user,
):
    owner_tenant = await make_tenant(name="Owner tenant")
    other_tenant = await make_tenant(name="Other tenant")
    owner = await make_user(owner_tenant, role="methodologist")
    outsider = await make_user(other_tenant, role="methodologist")

    create_response = await client.post(
        "/api/v1/learning-paths",
        headers=auth_headers(owner),
        json={"title": "Private program", "sequencing_mode": "linear"},
    )
    assert create_response.status_code == 201
    path_id = create_response.json()["id"]

    response = await client.get(
        f"/api/v1/learning-paths/{path_id}",
        headers=auth_headers(outsider),
    )
    assert response.status_code == 404


async def test_learning_program_assignment_rejects_cross_tenant_learner(
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
):
    owner_tenant = await make_tenant(name="Assignment owner")
    other_tenant = await make_tenant(name="Assignment outsider")
    methodologist = await make_user(owner_tenant, role="methodologist")
    outsider = await make_user(other_tenant, role="student")
    path_id = uuid4()
    await set_current_tenant(owner_tenant)
    db_session.add(
        LearningPath(
            id=path_id,
            tenant_id=owner_tenant.id,
            family_id=uuid4(),
            version=1,
            title="Tenant-bound program",
            description="",
            status="published",
            sequencing_mode="linear",
            created_by=methodologist.id,
        )
    )
    await db_session.flush()

    with pytest.raises(DBAPIError, match="learner must belong to the same tenant"):
        async with db_session.begin_nested():
            db_session.add(
                LearningPathAssignment(
                    tenant_id=owner_tenant.id,
                    path_id=path_id,
                    user_id=outsider.id,
                    assigned_by=methodologist.id,
                )
            )
            await db_session.flush()
