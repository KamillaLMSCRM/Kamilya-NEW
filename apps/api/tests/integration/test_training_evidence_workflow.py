"""Integration tests for evidence created by real learning workflows."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.modules.certificates.models import Certificate
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.quizzes.models import Question, QuizAttempt, QuizChoice
from app.modules.student.service import get_student_dashboard
from app.modules.training_evidence.models import TrainingEvidenceEvent
from app.modules.training_evidence.service import record_event
from app.modules.training_evidence.step_up_service import _canonical_confirmation
from app.modules.training_evidence.workflow import (
    record_course_completion,
    record_quiz_submission,
)

pytestmark = pytest.mark.asyncio


async def _release_for(db_session, tenant, course, author):
    snapshot = {
        "schema_version": 1,
        "course": {"id": str(course.id), "title": course.title},
        "modules": [],
    }
    release = ContentRelease(
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot=snapshot,
        snapshot_sha256=canonical_json_sha256(snapshot),
        published_by=author.id,
    )
    db_session.add(release)
    await db_session.flush()
    course.current_release_id = release.id
    await db_session.flush()
    return release


async def test_course_completion_workflow_is_idempotent(
    db_session,
    make_tenant,
    make_user,
    make_course,
):
    tenant = await make_tenant(name="Completion workflow tenant")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-completion@evidence.example",
    )
    course = await make_course(tenant, methodologist, title="Completion course", status="published")
    release = await _release_for(db_session, tenant, course, methodologist)
    learner = await make_user(tenant, role="student", email="learner-completion@evidence.example")
    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        content_release_id=release.id,
        status="completed",
        source="manual",
    )
    certificate = Certificate(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        certificate_number="KML-TEST-COMPLETION",
    )
    db_session.add_all([enrollment, certificate])
    await db_session.flush()

    first = await record_course_completion(
        db_session,
        user=learner,
        course=course,
        enrollment=enrollment,
        certificate=certificate,
    )
    retry = await record_course_completion(
        db_session,
        user=learner,
        course=course,
        enrollment=enrollment,
        certificate=certificate,
    )

    assert retry.id == first.id
    assert first.procedure_type == "training"
    assert first.source_event_key == f"course-completion:{enrollment.id}"
    assert first.enrollment_id == enrollment.id
    assert first.content_release_id == release.id
    assert first.payload_snapshot["certificate_id"] == str(certificate.id)
    statement, object_version = _canonical_confirmation(first)
    assert statement == (
        "Я подтверждаю, что завершил(а) курс „Completion course“ "
        "и ознакомился(лась) с материалами опубликованной версии 1."
    )
    assert object_version == f"release:{release.version}"
    assert first.payload_snapshot["content_release_sha256"] == release.snapshot_sha256
    assert (
        await db_session.scalar(
            select(TrainingEvidenceEvent.id).where(TrainingEvidenceEvent.source_event_key == first.source_event_key)
        )
        == first.id
    )


async def test_student_dashboard_exposes_enrollment_id_for_resumable_confirmation(
    db_session,
    make_tenant,
    make_user,
    make_course,
):
    tenant = await make_tenant(name="Resumable confirmation tenant")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-resume@evidence.example",
    )
    learner = await make_user(tenant, role="student", email="learner-resume@evidence.example")
    course = await make_course(tenant, methodologist, title="Resumable course", status="published")
    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        status="completed",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()

    dashboard = await get_student_dashboard(db_session, learner.id, tenant.id)

    assert dashboard["enrolled_courses"][0]["enrollment_id"] == enrollment.id


async def test_course_completion_route_creates_training_evidence(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
):
    tenant = await make_tenant(name="Completion route tenant")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-completion-route@evidence.example",
    )
    learner = await make_user(
        tenant,
        role="student",
        email="learner-completion-route@evidence.example",
    )
    course = await make_course(tenant, methodologist, title="Completion route course")
    module = await make_module(course, title="Module")
    lesson = await make_lesson(module, title="Lesson", content="Training content")
    course.status = "published"
    release = await _release_for(db_session, tenant, course, methodologist)
    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        content_release_id=release.id,
        status="in_progress",
        source="manual",
    )
    db_session.add_all(
        [
            enrollment,
            Progress(
                tenant_id=tenant.id,
                user_id=learner.id,
                course_id=course.id,
                lesson_id=lesson.id,
                completed=True,
                completion_percent=100,
                percent=100,
            ),
        ]
    )
    await db_session.flush()

    response = await client.post(
        f"/api/v1/courses/{course.id}/complete",
        headers=auth_headers(learner),
    )

    assert response.status_code == 200, response.text
    response_event_id = response.json()["training_evidence_event_id"]
    event = await db_session.scalar(
        select(TrainingEvidenceEvent).where(
            TrainingEvidenceEvent.tenant_id == tenant.id,
            TrainingEvidenceEvent.procedure_type == "training",
            TrainingEvidenceEvent.enrollment_id == enrollment.id,
        )
    )
    assert event is not None
    assert response_event_id == str(event.id)
    assert event.source_event_key == f"course-completion:{enrollment.id}"
    assert event.content_release_id == release.id

    retry = await client.post(
        f"/api/v1/courses/{course.id}/complete",
        headers=auth_headers(learner),
    )
    assert retry.status_code == 200, retry.text
    assert (
        await db_session.scalar(
            select(TrainingEvidenceEvent.id).where(TrainingEvidenceEvent.source_event_key == event.source_event_key)
        )
        == event.id
    )


async def test_saved_quiz_attempt_creates_knowledge_check_without_admission(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    tenant = await make_tenant(name="Quiz workflow tenant")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-quiz@evidence.example",
    )
    learner = await make_user(tenant, role="student", email="learner-quiz@evidence.example")
    course = await make_course(tenant, methodologist, title="Quiz course", status="published")
    module = await make_module(course, title="Module")
    lesson = await make_lesson(module, title="Lesson", content="Policy")
    quiz = await make_quiz(lesson, title="Knowledge check")
    release = await _release_for(db_session, tenant, course, methodologist)
    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        content_release_id=release.id,
        status="in_progress",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()
    attempt_id = uuid4()
    snapshot = {
        "attempt": {
            "id": str(attempt_id),
            "tenant_id": str(tenant.id),
            "user_id": str(learner.id),
            "enrollment_id": str(enrollment.id),
            "course_id": str(course.id),
            "content_release_id": str(release.id),
            "content_release_sha256": release.snapshot_sha256,
        }
    }
    attempt = QuizAttempt(
        id=attempt_id,
        quiz_id=quiz.id,
        user_id=learner.id,
        tenant_id=tenant.id,
        enrollment_id=enrollment.id,
        content_release_id=release.id,
        score_percent=100,
        total_points=1,
        earned_points=1,
        passed=True,
        answers=[],
        evidence_snapshot=snapshot,
        evidence_sha256=canonical_json_sha256(snapshot),
    )
    db_session.add(attempt)
    await db_session.flush()

    event = await record_quiz_submission(db_session, user=learner, attempt=attempt)

    assert event.procedure_type == "knowledge_check"
    assert event.enrollment_id == enrollment.id
    assert event.content_release_id == release.id
    assert event.payload_snapshot["attempt_evidence"]["attempt_id"] == str(attempt.id)
    assert event.payload_snapshot["attempt_evidence"]["evidence_sha256"] == attempt.evidence_sha256
    assert event.payload_snapshot["passed"] is True
    statement, object_version = _canonical_confirmation(event)
    assert statement == (
        "Я подтверждаю, что прошел(ла) тест „Knowledge check“ по опубликованной версии 1; "
        "зафиксированный результат 100%, статус пройден."
    )
    assert object_version == f"release:{release.version}"
    assert event.payload_snapshot["content_release_sha256"] == release.snapshot_sha256
    assert (
        await db_session.scalar(
            select(TrainingEvidenceEvent).where(
                TrainingEvidenceEvent.tenant_id == tenant.id,
                TrainingEvidenceEvent.procedure_type == "admission_decision",
            )
        )
        is None
    )


async def test_quiz_submission_route_creates_knowledge_check_evidence(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
):
    tenant = await make_tenant(name="Quiz route tenant")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-quiz-route@evidence.example",
    )
    learner = await make_user(tenant, role="student", email="learner-quiz-route@evidence.example")
    course = await make_course(tenant, methodologist, title="Quiz route course", status="published")
    module = await make_module(course, title="Module")
    lesson = await make_lesson(module, title="Lesson", content="Knowledge check content")
    quiz = await make_quiz(lesson, title="Knowledge check", pass_score=80)
    question = Question(quiz_id=quiz.id, text="What is correct?", type="MCQ", points=1, order_index=0)
    db_session.add(question)
    await db_session.flush()
    correct = QuizChoice(question_id=question.id, text="Correct", is_correct=True, order_index=0)
    wrong = QuizChoice(question_id=question.id, text="Wrong", is_correct=False, order_index=1)
    db_session.add_all([correct, wrong])
    release = await _release_for(db_session, tenant, course, methodologist)
    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        content_release_id=release.id,
        status="in_progress",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        headers=auth_headers(learner),
        json={
            "answers": [
                {
                    "question_id": str(question.id),
                    "selected_choice_ids": [str(correct.id)],
                }
            ],
            "time_spent_seconds": 12,
        },
    )

    assert response.status_code == 200, response.text
    response_body = response.json()
    attempt_id = response_body["attempt"]["id"]
    assert set(response_body) == {"attempt", "passed", "message", "training_evidence_event_id"}
    assert "answers" not in response_body["attempt"]
    assert "correct_choice_ids" not in response.text
    assert "is_correct" not in response.text
    assert "explanation" not in response.text
    event = await db_session.scalar(
        select(TrainingEvidenceEvent).where(TrainingEvidenceEvent.source_event_key == f"quiz-attempt:{attempt_id}")
    )
    assert event is not None
    assert response_body["training_evidence_event_id"] == str(event.id)
    assert event.procedure_type == "knowledge_check"
    assert event.enrollment_id == enrollment.id
    assert event.content_release_id == release.id
    assert event.payload_snapshot["passed"] is True
    statement, object_version = _canonical_confirmation(event)
    assert statement == (
        "Я подтверждаю, что прошел(ла) тест „Knowledge check“ по опубликованной версии 1; "
        "зафиксированный результат 100%, статус пройден."
    )
    assert object_version == f"release:{release.version}"
    assert (
        await db_session.scalar(
            select(TrainingEvidenceEvent.id).where(
                TrainingEvidenceEvent.procedure_type == "admission_decision",
                TrainingEvidenceEvent.tenant_id == tenant.id,
            )
        )
        is None
    )


async def test_same_source_key_with_different_snapshot_is_conflict(
    db_session,
    make_tenant,
    make_user,
    make_course,
):
    tenant = await make_tenant(name="Idempotency conflict tenant")
    actor = await make_user(tenant, role="methodologist", email="idempotency@evidence.example")
    await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        user_id=actor.id,
        procedure_type="training",
        source_event_key="workflow-retry-1",
        payload_snapshot={"value": 1},
    )

    with pytest.raises(HTTPException) as exc_info:
        await record_event(
            db_session,
            tenant_id=tenant.id,
            actor_user_id=actor.id,
            user_id=actor.id,
            procedure_type="training",
            source_event_key="workflow-retry-1",
            payload_snapshot={"value": 2},
        )
    assert exc_info.value.status_code == 409

    different_subject = await make_user(tenant, role="student", email="idempotency-subject@evidence.example")
    with pytest.raises(HTTPException) as subject_conflict:
        await record_event(
            db_session,
            tenant_id=tenant.id,
            actor_user_id=different_subject.id,
            user_id=different_subject.id,
            procedure_type="training",
            source_event_key="workflow-retry-1",
            payload_snapshot={"value": 1},
        )
    assert subject_conflict.value.status_code == 409

    course = await make_course(tenant, actor, title="Idempotency link course")
    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=actor.id,
        status="enrolled",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()
    with pytest.raises(HTTPException) as link_conflict:
        await record_event(
            db_session,
            tenant_id=tenant.id,
            actor_user_id=actor.id,
            user_id=actor.id,
            enrollment_id=enrollment.id,
            procedure_type="training",
            source_event_key="workflow-retry-1",
            payload_snapshot={"value": 1},
        )
    assert link_conflict.value.status_code == 409

    with pytest.raises(HTTPException) as procedure_conflict:
        await record_event(
            db_session,
            tenant_id=tenant.id,
            actor_user_id=actor.id,
            user_id=actor.id,
            procedure_type="knowledge_check",
            source_event_key="workflow-retry-1",
            payload_snapshot={"value": 1},
        )
    assert procedure_conflict.value.status_code == 409

    other_tenant = await make_tenant(name="Idempotency other tenant")
    other_actor = await make_user(other_tenant, role="methodologist", email="idempotency-other@evidence.example")
    other_event = await record_event(
        db_session,
        tenant_id=other_tenant.id,
        actor_user_id=other_actor.id,
        user_id=other_actor.id,
        procedure_type="training",
        source_event_key="workflow-retry-1",
        payload_snapshot={"value": 2},
    )
    assert other_event.tenant_id == other_tenant.id


async def test_course_completion_route_rejects_missing_release_before_certificate(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
):
    tenant = await make_tenant(name="Missing release tenant")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-missing-release@evidence.example",
    )
    learner = await make_user(tenant, role="student", email="learner-missing-release@evidence.example")
    course = await make_course(tenant, methodologist, title="Missing release course")
    module = await make_module(course, title="Module")
    lesson = await make_lesson(module, title="Lesson", content="Training content")
    db_session.add(
        Progress(
            tenant_id=tenant.id,
            user_id=learner.id,
            course_id=course.id,
            lesson_id=lesson.id,
            completed=True,
            completion_percent=100,
            percent=100,
        )
    )
    await db_session.flush()

    response = await client.post(
        f"/api/v1/courses/{course.id}/complete",
        headers=auth_headers(learner),
    )

    assert response.status_code == 400
    assert "immutable ContentRelease" in response.json()["message"]
    assert (
        await db_session.scalar(
            select(Certificate.id).where(
                Certificate.tenant_id == tenant.id,
                Certificate.user_id == learner.id,
                Certificate.course_id == course.id,
            )
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(TrainingEvidenceEvent.id).where(
                TrainingEvidenceEvent.tenant_id == tenant.id,
                TrainingEvidenceEvent.user_id == learner.id,
                TrainingEvidenceEvent.procedure_type == "training",
            )
        )
        is None
    )


async def test_database_unique_constraint_is_concurrency_backstop(
    db_session,
    make_tenant,
    make_user,
):
    tenant = await make_tenant(name="Idempotency race tenant")
    actor = await make_user(tenant, role="methodologist", email="race@evidence.example")
    first = TrainingEvidenceEvent(
        tenant_id=tenant.id,
        user_id=actor.id,
        procedure_type="training",
        source_event_key="same-key",
        payload_snapshot={"value": 1},
        payload_sha256=canonical_json_sha256({"value": 1}),
        recorded_by_user_id=actor.id,
    )
    second = TrainingEvidenceEvent(
        tenant_id=tenant.id,
        user_id=actor.id,
        procedure_type="training",
        source_event_key="same-key",
        payload_snapshot={"value": 1},
        payload_sha256=canonical_json_sha256({"value": 1}),
        recorded_by_user_id=actor.id,
    )
    savepoint = await db_session.begin_nested()
    try:
        db_session.add_all([first, second])
        with pytest.raises(DBAPIError):
            await db_session.flush()
    finally:
        await savepoint.rollback()
