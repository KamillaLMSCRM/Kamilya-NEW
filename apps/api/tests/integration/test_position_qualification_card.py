"""Integration coverage for the unified position qualification card."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.positions.qualification_models import PositionQualificationVersion
from app.modules.positions.qualification_schemas import (
    PositionQualificationCard,
    QualificationCompetenciesPut,
    QualificationProfilePatch,
    QualificationTrainingPut,
)


def test_qualification_schema_contract() -> None:
    profile = QualificationProfilePatch(name="Operator", change_reason="Annual review")
    assert set(profile.model_dump(exclude_unset=True)) == {"name", "change_reason"}

    competencies = QualificationCompetenciesPut(
        items=[{"competency_id": uuid4(), "required_level": 5}],
        change_reason="Role matrix update",
    )
    assert competencies.items[0].required_level == 5

    training = QualificationTrainingPut(
        items=[{"course_id": uuid4(), "required": False}],
        change_reason="Optional refresher",
    )
    assert training.items[0].required is False

    card = PositionQualificationCard.model_validate(
        {
            "profile": {
                "id": uuid4(),
                "tenant_id": uuid4(),
                "name": "Operator",
                "department": "Operations",
                "level": "Senior",
                "responsibilities": "Operate equipment",
                "requirements": "Training",
                "employee_count": 2,
                "current_employee_count": 1,
                "created_at": None,
            },
            "instruction": None,
            "competencies": [],
            "training": {
                "position_courses": [],
                "department_courses": [],
                "competency_courses": [],
                "effective_courses": [],
            },
            "onboarding_quiz": None,
            "employees": {"active_count": 1},
            "latest_version": None,
            "history_count": 0,
        }
    )
    assert card.profile.current_employee_count == 1


@pytest.mark.asyncio
async def test_qualification_card_aggregates_sources(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    from app.models.department import Department
    from app.modules.competencies.models import Competency, CompetencyCourse, PositionCompetency
    from app.modules.positions.models import DepartmentCourse, Position, PositionCourse, PositionQuiz

    tenant = await make_tenant(name="Qualification tenant", slug="qualification-card")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist@qualification.example")
    employee = await make_user(tenant, role="student", email="employee@qualification.example")
    department = Department(
        id=uuid4(), tenant_id=tenant.id, name="Operations", slug="operations", description=""
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Operator",
        department="Operations",
        department_id=department.id,
        level="Senior",
        responsibilities="Operate equipment",
        requirements="Safety training",
        employee_count=1,
    )
    db_session.add_all([department, position])
    await db_session.flush()
    employee.position_id = position.id
    await db_session.flush()
    position_course = await make_course(tenant, methodologist, title="Position safety", status="draft")
    department_course = await make_course(tenant, methodologist, title="Department induction", status="published")
    competency_course = await make_course(tenant, methodologist, title="Equipment competency", status="published")
    competency = Competency(
        id=uuid4(), tenant_id=tenant.id, name="Equipment operation", description="Can operate equipment"
    )
    db_session.add_all(
        [
            PositionCourse(
                tenant_id=tenant.id, position_id=position.id,
                course_id=position_course.id, required=False,
            ),
            DepartmentCourse(
                id=uuid4(), tenant_id=tenant.id, department_id=department.id,
                course_id=department_course.id, required=True,
            ),
            competency,
            PositionCompetency(
                id=uuid4(), tenant_id=tenant.id, position_id=position.id,
                competency_id=competency.id, required_level=4,
            ),
            CompetencyCourse(
                id=uuid4(), tenant_id=tenant.id, competency_id=competency.id,
                course_id=competency_course.id,
            ),
            PositionQuiz(
                id=uuid4(), tenant_id=tenant.id, position_id=position.id,
                title="Operator onboarding", pass_score=80, time_limit=15,
                questions=[{"text": "Question", "choices": [{"text": "A", "is_correct": True}]}],
                is_active=True,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/positions/{position.id}/qualification-card",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"]["name"] == "Operator"
    assert body["profile"]["current_employee_count"] == 1
    assert body["competencies"][0]["required_level"] == 4
    assert str(competency_course.id) in body["competencies"][0]["course_ids"]
    assert {item["source"] for item in body["training"]["position_courses"]} == {"position"}
    assert {item["source"] for item in body["training"]["department_courses"]} == {"department"}
    assert {item["source"] for item in body["training"]["competency_courses"]} == {"competency"}
    assert body["onboarding_quiz"]["question_count"] == 1


@pytest.mark.asyncio
async def test_qualification_mutations_create_immutable_versions_and_audit(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    from app.modules.audit.models import AuditLog
    from app.modules.positions.models import Position

    tenant = await make_tenant(name="Mutation tenant", slug="qualification-mutation")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist@mutation.example")
    position = Position(
        id=uuid4(), tenant_id=tenant.id, name="Old name", department="Operations",
        level="Junior", responsibilities="Old responsibilities", requirements="Old requirements",
        employee_count=0,
    )
    course = await make_course(tenant, methodologist, title="Mandatory course", status="draft")
    db_session.add(position)
    await db_session.flush()

    profile_response = await client.patch(
        f"/api/v1/positions/{position.id}/qualification-profile",
        json={"name": "New name", "change_reason": "Reorg"},
        headers=auth_headers(methodologist),
    )
    assert profile_response.status_code == 200, profile_response.text
    assert profile_response.json()["profile"]["name"] == "New name"
    assert profile_response.json()["latest_version"] == 2
    assert profile_response.json()["history_count"] == 2

    training_response = await client.put(
        f"/api/v1/positions/{position.id}/mandatory-training",
        json={"items": [{"course_id": str(course.id), "required": True}], "change_reason": "Required"},
        headers=auth_headers(methodologist),
    )
    assert training_response.status_code == 200, training_response.text
    assert training_response.json()["latest_version"] == 3

    no_op_response = await client.put(
        f"/api/v1/positions/{position.id}/mandatory-training",
        json={"items": [{"course_id": str(course.id), "required": True}]},
        headers=auth_headers(methodologist),
    )
    assert no_op_response.status_code == 200, no_op_response.text
    assert no_op_response.json()["latest_version"] == 3
    assert no_op_response.json()["history_count"] == 3

    history_response = await client.get(
        f"/api/v1/positions/{position.id}/qualification-history",
        headers=auth_headers(methodologist),
    )
    assert history_response.status_code == 200
    assert [item["version_no"] for item in history_response.json()["items"]] == [3, 2, 1]
    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.resource_type == "position_qualification",
            )
        )
    ).scalars().all()
    assert {row.action for row in audit_rows} == {
        "position_qualification_profile_update",
        "position_qualification_training_update",
    }


@pytest.mark.asyncio
async def test_qualification_tenant_scope_and_input_validation(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    from app.modules.competencies.models import Competency
    from app.modules.positions.models import Position

    tenant_a = await make_tenant(name="Tenant A", slug="qualification-a")
    tenant_b = await make_tenant(name="Tenant B", slug="qualification-b")
    method_a = await make_user(tenant_a, role="methodologist", email="method-a@qualification.example")
    method_b = await make_user(tenant_b, role="methodologist", email="method-b@qualification.example")
    course_a = await make_course(tenant_a, method_a, title="A course")
    course_b = await make_course(tenant_b, method_b, title="B course")
    competency_a = Competency(id=uuid4(), tenant_id=tenant_a.id, name="A competency", description="")
    position_b = Position(id=uuid4(), tenant_id=tenant_b.id, name="B position", department="", level="")
    db_session.add_all([competency_a, position_b])
    await db_session.flush()

    hidden = await client.get(
        f"/api/v1/positions/{position_b.id}/qualification-card",
        headers=auth_headers(method_a),
    )
    assert hidden.status_code == 404

    invalid_course = await client.put(
        f"/api/v1/positions/{position_b.id}/mandatory-training",
        json={"items": [{"course_id": str(course_a.id)}]},
        headers=auth_headers(method_b),
    )
    assert invalid_course.status_code == 422
    assert invalid_course.json()["details"]["code"] == "course_outside_tenant"

    invalid_competency = await client.put(
        f"/api/v1/positions/{position_b.id}/qualification-competencies",
        json={"items": [{"competency_id": str(competency_a.id), "required_level": 3}]},
        headers=auth_headers(method_b),
    )
    assert invalid_competency.status_code == 422
    assert invalid_competency.json()["details"]["code"] == "competency_outside_tenant"
    assert course_b.tenant_id == tenant_b.id


@pytest.mark.asyncio
async def test_qualification_restore_rejects_missing_snapshot_reference(
    client, db_session, make_tenant, make_user, auth_headers
):
    from app.modules.positions.models import Position

    tenant = await make_tenant(name="Restore tenant", slug="qualification-restore")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist@restore.example")
    position = Position(id=uuid4(), tenant_id=tenant.id, name="Restore", department="", level="")
    version = PositionQualificationVersion(
        id=uuid4(), tenant_id=tenant.id, position_id=position.id, version_no=1,
        snapshot={
            "profile": {"name": "Restore", "department": "", "level": "", "responsibilities": "", "requirements": ""},
            "instruction_document_id": str(uuid4()),
            "competencies": [], "training": {"position_courses": []}, "onboarding_quiz": None,
        },
        change_kind="baseline",
    )
    db_session.add_all([position, version])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/positions/{position.id}/qualification-history/{version.id}/restore",
        json={"change_reason": "Try restore"},
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 409
    assert response.json()["details"]["code"] == "snapshot_reference_missing"


@pytest.mark.asyncio
async def test_qualification_role_dependency_and_route_uniqueness(
    client, make_tenant, make_user, auth_headers
):
    from app.modules.positions.models import Position
    from app.modules.positions.qualification_router import router

    tenant = await make_tenant(name="RBAC tenant", slug="qualification-rbac")
    student = await make_user(tenant, role="student", email="student@qualification.example")
    admin = await make_user(tenant, role="admin", email="admin@qualification.example")
    position = Position(id=uuid4(), tenant_id=tenant.id, name="RBAC", department="", level="")
    unauthenticated = await client.get(f"/api/v1/positions/{position.id}/qualification-card")
    assert unauthenticated.status_code == 401
    forbidden = await client.get(
        f"/api/v1/positions/{position.id}/qualification-card",
        headers=auth_headers(student),
    )
    assert forbidden.status_code == 403
    admin_forbidden = await client.get(
        f"/api/v1/positions/{position.id}/qualification-card",
        headers=auth_headers(admin),
    )
    assert admin_forbidden.status_code == 403
    matching = [
        route.path
        for route in router.routes
        if getattr(route, "path", None) == "/api/v1/positions/{position_id}/qualification-card"
    ]
    assert matching == []
    matching = [
        route.path
        for route in router.routes
        if getattr(route, "path", None) == "/positions/{position_id}/qualification-card"
    ]
    assert matching == ["/positions/{position_id}/qualification-card"]


@pytest.mark.asyncio
async def test_restore_recreates_deleted_onboarding_quiz(
    client, db_session, make_tenant, make_user, auth_headers
):
    from app.modules.positions.models import Position, PositionQuiz

    tenant = await make_tenant(name="Quiz restore tenant", slug="qualification-quiz-restore")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@quiz-restore.example",
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Operator",
        department="Operations",
        level="Junior",
    )
    quiz_id = uuid4()
    version = PositionQualificationVersion(
        id=uuid4(),
        tenant_id=tenant.id,
        position_id=position.id,
        version_no=1,
        snapshot={
            "profile": {
                "name": "Operator",
                "department": "Operations",
                "level": "Junior",
                "responsibilities": "",
                "requirements": "",
            },
            "instruction_document_id": None,
            "competencies": [],
            "training": {"position_courses": []},
            "onboarding_quiz": {
                "id": str(quiz_id),
                "title": "Operator onboarding",
                "pass_score": 85,
                "time_limit": 20,
                "questions": [
                    {
                        "text": "Safety check?",
                        "type": "MCQ",
                        "explanation": "",
                        "choices": [
                            {"text": "Yes", "is_correct": True},
                            {"text": "No", "is_correct": False},
                        ],
                    }
                ],
                "is_active": True,
            },
        },
        change_kind="baseline",
        created_by=methodologist.id,
    )
    db_session.add_all([position, version])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/positions/{position.id}/qualification-history/{version.id}/restore",
        json={"change_reason": "Restore deleted onboarding quiz"},
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200, response.text
    assert response.json()["onboarding_quiz"]["title"] == "Operator onboarding"
    restored = await db_session.scalar(
        select(PositionQuiz).where(
            PositionQuiz.id == quiz_id,
            PositionQuiz.tenant_id == tenant.id,
        )
    )
    assert restored is not None


@pytest.mark.asyncio
async def test_existing_onboarding_editor_records_qualification_history(
    client, db_session, make_tenant, make_user, auth_headers
):
    from app.modules.positions.models import Position

    tenant = await make_tenant(name="Quiz history tenant", slug="qualification-quiz-history")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@quiz-history.example",
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Operator",
        department="Operations",
        level="Junior",
    )
    db_session.add(position)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/positions/{position.id}/onboarding-quiz",
        json={
            "title": "Operator onboarding",
            "pass_score": 80,
            "time_limit": 15,
            "is_active": True,
            "questions": [
                {
                    "text": "Use PPE?",
                    "type": "MCQ",
                    "explanation": "PPE is mandatory.",
                    "choices": [
                        {"text": "Yes", "is_correct": True},
                        {"text": "No", "is_correct": False},
                    ],
                }
            ],
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200, response.text

    history_response = await client.get(
        f"/api/v1/positions/{position.id}/qualification-history",
        headers=auth_headers(methodologist),
    )
    assert history_response.status_code == 200
    assert [
        item["change_kind"] for item in history_response.json()["items"]
    ] == ["onboarding_quiz_update", "baseline"]


@pytest.mark.asyncio
async def test_existing_jd_restore_records_qualification_history(
    client, db_session, make_tenant, make_user, auth_headers
):
    from app.modules.positions.models import Position, PositionJDVersion

    tenant = await make_tenant(name="JD history tenant", slug="qualification-jd-history")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@jd-history.example",
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Operator",
        department="Operations",
        level="Junior",
        responsibilities="Current responsibilities",
        requirements="Current requirements",
    )
    historical_version = PositionJDVersion(
        id=uuid4(),
        tenant_id=tenant.id,
        position_id=position.id,
        responsibilities="Historical responsibilities",
        requirements="Historical requirements",
        source="manual",
        created_by=methodologist.id,
    )
    db_session.add_all([position, historical_version])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/positions/{position.id}/restore-jd/{historical_version.id}",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200, response.text
    assert response.json()["position"]["responsibilities"] == "Historical responsibilities"

    history_response = await client.get(
        f"/api/v1/positions/{position.id}/qualification-history",
        headers=auth_headers(methodologist),
    )
    assert history_response.status_code == 200
    assert [
        item["change_kind"] for item in history_response.json()["items"]
    ] == ["instruction_restore", "baseline"]
