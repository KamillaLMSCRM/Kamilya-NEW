"""Integration coverage for server-built training-evidence downloads."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from pypdf import PdfReader
from sqlalchemy import select

from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.training_evidence.service import add_legal_hold, confirm_step_up, record_event

pytestmark = pytest.mark.asyncio


async def _make_complete_event(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    *,
    tenant_name: str = "Export tenant",
    procedure_type: str = "knowledge_check",
):
    from app.models.enrollment import Enrollment
    from app.modules.quizzes.models import QuizAttempt

    tenant = await make_tenant(name=tenant_name)
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email=f"methodologist-{uuid4().hex[:8]}@evidence.example",
        first_name="Method",
        last_name="Ologist",
    )
    learner = await make_user(
        tenant,
        role="student",
        email=f"learner-{uuid4().hex[:8]}@evidence.example",
        first_name="Aliya",
        last_name="Akhmetova",
        personnel_number="EMP-007",
    )
    course = await make_course(tenant, methodologist, title="Internal microcredit rules")
    module = await make_module(course, title="Rules")
    lesson = await make_lesson(module, title="Knowledge check")
    quiz = await make_quiz(lesson, title="Microcredit quiz", pass_score=80)

    release_snapshot = {
        "schema_version": 1,
        "course": {"id": str(course.id), "title": course.title},
        "modules": [{"id": str(module.id), "lessons": [{"id": str(lesson.id)}]}],
    }
    release = ContentRelease(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot=release_snapshot,
        snapshot_sha256=canonical_json_sha256(release_snapshot),
        published_by=methodologist.id,
        published_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    course.current_release_id = release.id
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        content_release_id=release.id,
        status="enrolled",
        source="position",
        enrolled_at=datetime.now(UTC),
    )
    db_session.add(enrollment)
    await db_session.flush()

    attempt_id = uuid4()
    completed_at = datetime.now(UTC)
    graded_answers = [{"question_id": "q-1", "answer": "a", "is_correct": True}]
    attempt_snapshot = {
        "schema_version": 1,
        "attempt": {
            "id": str(attempt_id),
            "tenant_id": str(tenant.id),
            "user_id": str(learner.id),
            "enrollment_id": str(enrollment.id),
            "content_release_id": str(release.id),
            "quiz_id": str(quiz.id),
        },
        "quiz": {"id": str(quiz.id), "title": quiz.title, "pass_score": quiz.pass_score},
        "graded_answers": graded_answers,
    }
    attempt = QuizAttempt(
        id=attempt_id,
        tenant_id=tenant.id,
        user_id=learner.id,
        quiz_id=quiz.id,
        enrollment_id=enrollment.id,
        content_release_id=release.id,
        score_percent=100,
        total_points=1,
        earned_points=1,
        passed=True,
        answers=graded_answers,
        evidence_snapshot=attempt_snapshot,
        evidence_sha256=canonical_json_sha256(attempt_snapshot),
        started_at=completed_at - timedelta(minutes=10),
        completed_at=completed_at,
        time_spent_seconds=600,
    )
    db_session.add(attempt)
    await db_session.flush()

    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner.id,
        procedure_type=procedure_type,
        enrollment_id=enrollment.id,
        content_release_id=release.id,
        payload_snapshot={
            "procedure": {
                "title": "Проверка знаний правил предоставления микрокредитов",
                "code": "MICRO-2025",
                "version": "1.0",
            }
        },
    )
    await confirm_step_up(
        db_session,
        tenant_id=tenant.id,
        event_id=event.id,
        user_id=learner.id,
        action_text="Подтверждаю результат проверки знаний, версия 1.0",
        object_version="content-release:v1",
        reauth_method="email_otp",
        ip_address="192.0.2.10",
        user_agent="evidence-test/1.0",
    )
    await db_session.flush()
    return tenant, methodologist, learner, event, release, enrollment


async def test_individual_export_builds_server_owned_zip_and_state(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    auth_headers,
):
    tenant, methodologist, learner, event, _, _ = await _make_complete_event(
        db_session, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz
    )
    await add_legal_hold(
        db_session,
        tenant_id=tenant.id,
        event_id=event.id,
        actor_user_id=methodologist.id,
        action="placed",
        reason="Проверка комплаенса",
    )
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="kamilya-')
    assert all(ord(char) < 128 for char in disposition)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["employee"]["id"] == str(learner.id)
    assert manifest["course"]["release_id"]
    assert manifest["attempts"][0]["answers"]
    assert manifest["state"]["legal_hold_active"] is True
    assert manifest["confirmation"]["method"] == "otp"

    repeated = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(methodologist),
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.content == response.content

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        pdf_text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(archive.read("individual-act.pdf"))).pages
        )
    assert "Состояние доказательства" in pdf_text
    assert "Юридическое удержание: Активно" in pdf_text


async def test_pdf_format_is_streamed_without_public_mode(client, complete_event, auth_headers):
    _, methodologist, _, event, _, _ = complete_event
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export?format=pdf",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
    assert "public" not in response.headers["content-disposition"].lower()


async def test_missing_mandatory_evidence_returns_409(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Incomplete export")
    methodologist = await make_user(tenant, role="methodologist", email="incomplete-method@evidence.example")
    learner = await make_user(tenant, role="student", email="incomplete-learner@evidence.example")
    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner.id,
        procedure_type="knowledge_check",
        payload_snapshot={"procedure": {"title": "Incomplete"}},
    )
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 409
    assert response.json()["details"]["code"] == "evidence_incomplete"
    assert "enrollment" in response.json()["details"]["missing"]


async def test_cross_tenant_admin_and_student_are_rejected(
    client,
    complete_event,
    make_tenant,
    make_user,
    auth_headers,
):
    tenant, methodologist, learner, event, _, _ = complete_event
    other_tenant = await make_tenant(name="Other export tenant")
    other_methodologist = await make_user(other_tenant, role="methodologist", email="other-method@evidence.example")
    admin = await make_user(tenant, role="admin", email="export-admin@evidence.example")

    cross_tenant = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/export",
        headers=auth_headers(other_methodologist),
    )
    assert cross_tenant.status_code == 404
    assert (
        await client.get(
            f"/api/v1/training-evidence/events/{event.id}/export",
            headers=auth_headers(admin),
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/training-evidence/events/{event.id}/export",
            headers=auth_headers(learner),
        )
    ).status_code == 403
    assert methodologist.role == "methodologist"


async def test_group_export_rejects_duplicate_and_oversized_requests(client, complete_event, auth_headers):
    _, methodologist, _, event, _, _ = complete_event
    duplicate = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": [str(event.id), str(event.id)]},
    )
    assert duplicate.status_code == 422
    oversized = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": [str(uuid4()) for _ in range(201)]},
    )
    assert oversized.status_code == 422


async def test_group_export_rejects_malformed_event_id(client, complete_event, auth_headers):
    _, methodologist, _, _, _, _ = complete_event
    response = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": ["not-a-uuid"]},
    )
    assert response.status_code == 422


async def test_group_export_keeps_individual_decisions(
    client,
    db_session,
    complete_event,
    make_user,
    auth_headers,
):
    from app.models.enrollment import Enrollment
    from app.modules.evidence_export import build_group_evidence_package
    from app.modules.quizzes.models import QuizAttempt
    from app.modules.training_evidence.export_service import build_group_evidence_input

    tenant, methodologist, learner_one, event_one, release, enrollment_one = complete_event
    now = datetime.now(UTC)
    event_one_decided = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner_one.id,
        procedure_type=event_one.procedure_type,
        enrollment_id=enrollment_one.id,
        content_release_id=release.id,
        record_type="correction",
        related_event_id=event_one.id,
        reason="Record the individual admission decision.",
        payload_snapshot={
            **event_one.payload_snapshot,
            "decision": {
                "outcome": "admitted",
                "decided_at": now.isoformat(),
                "decided_by": str(methodologist.id),
                "rationale": "Passed the individual check.",
            },
        },
    )
    await confirm_step_up(
        db_session,
        tenant_id=tenant.id,
        event_id=event_one_decided.id,
        user_id=learner_one.id,
        action_text="Confirm individual result",
        object_version="content-release:v1",
        reauth_method="email_otp",
        ip_address="192.0.2.10",
        user_agent="evidence-test/1.0",
    )

    learner_two = await make_user(
        tenant,
        role="student",
        email=f"learner-{uuid4().hex[:8]}@evidence.example",
        first_name="Dana",
        last_name="Sarsenova",
        personnel_number="EMP-008",
    )
    enrollment_two = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=enrollment_one.course_id,
        user_id=learner_two.id,
        content_release_id=release.id,
        status="enrolled",
        source="position",
        enrolled_at=now,
    )
    db_session.add(enrollment_two)
    await db_session.flush()

    attempt_one = await db_session.scalar(
        select(QuizAttempt).where(QuizAttempt.enrollment_id == enrollment_one.id)
    )
    assert attempt_one is not None
    attempt_two_id = uuid4()
    attempt_two_snapshot = json.loads(json.dumps(attempt_one.evidence_snapshot))
    attempt_two_snapshot["attempt"].update(
        {
            "id": str(attempt_two_id),
            "user_id": str(learner_two.id),
            "enrollment_id": str(enrollment_two.id),
        }
    )
    attempt_two = QuizAttempt(
        id=attempt_two_id,
        tenant_id=tenant.id,
        user_id=learner_two.id,
        quiz_id=attempt_one.quiz_id,
        enrollment_id=enrollment_two.id,
        content_release_id=release.id,
        score_percent=70,
        total_points=attempt_one.total_points,
        earned_points=attempt_one.earned_points,
        passed=False,
        answers=attempt_one.answers,
        evidence_snapshot=attempt_two_snapshot,
        evidence_sha256=canonical_json_sha256(attempt_two_snapshot),
        started_at=now - timedelta(minutes=10),
        completed_at=now,
        time_spent_seconds=attempt_one.time_spent_seconds,
    )
    db_session.add(attempt_two)
    await db_session.flush()

    event_two = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner_two.id,
        procedure_type=event_one.procedure_type,
        enrollment_id=enrollment_two.id,
        content_release_id=release.id,
        payload_snapshot={
            "procedure": event_one.payload_snapshot["procedure"],
            "decision": {
                "outcome": "rejected",
                "decided_at": now.isoformat(),
                "decided_by": str(methodologist.id),
                "rationale": "Score below the threshold.",
            },
        },
    )
    await confirm_step_up(
        db_session,
        tenant_id=tenant.id,
        event_id=event_two.id,
        user_id=learner_two.id,
        action_text="Confirm individual result",
        object_version="content-release:v1",
        reauth_method="email_otp",
        ip_address="192.0.2.11",
        user_agent="evidence-test/1.0",
    )
    await db_session.flush()

    response = await client.post(
        "/api/v1/training-evidence/exports/group",
        headers=auth_headers(methodologist),
        json={"event_ids": [str(event_one_decided.id), str(event_two.id)]},
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert "group-protocol.pdf" in archive.namelist()

    outcomes = {
        record["employee"]["id"]: record["decision"]["outcome"]
        for record in manifest["records"]
    }
    assert outcomes[str(learner_one.id)] == "admitted"
    assert outcomes[str(learner_two.id)] == "rejected"
    assert manifest.get("decision") is None

    group_input = await build_group_evidence_input(
        db_session, tenant.id, [event_one_decided.id, event_two.id]
    )
    public_manifest = build_group_evidence_package(group_input, public=True).manifest
    assert all("decision" not in record for record in public_manifest["records"])
    assert public_manifest.get("decision") is None


@pytest_asyncio.fixture
async def complete_event(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    return await _make_complete_event(
        db_session,
        make_tenant,
        make_user,
        make_course,
        make_module,
        make_lesson,
        make_quiz,
    )
