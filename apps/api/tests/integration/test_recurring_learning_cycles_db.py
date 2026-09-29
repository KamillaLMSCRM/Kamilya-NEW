from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.modules.certificates.models import Certificate
from app.modules.certificates.service import issue_certificate
from app.modules.courses.release_service import ensure_course_release
from app.modules.learning_cycles import service as cycle_service
from app.modules.learning_cycles.models import (
    LearningCycleParticipantEvent,
    RecurringLearningAssignment,
    RecurringLearningRule,
)
from app.modules.progress.service import get_lesson_progress, update_lesson_progress
from app.modules.quizzes.models import QuizAttempt
from app.modules.quizzes.service import get_user_attempts


@pytest.mark.asyncio
async def test_recurring_schema_and_recovery_permissions(db_session):
    columns = set(
        (
            await db_session.execute(
                text(
                    """SELECT table_name,column_name FROM information_schema.columns
                    WHERE table_schema='public' AND (
                      (table_name='enrollments' AND column_name='recurring_assignment_id') OR
                      (table_name='progress' AND column_name='enrollment_id') OR
                      (table_name='certificates' AND column_name='enrollment_id'))"""
                )
            )
        ).all()
    )
    assert columns == {
        ("enrollments", "recurring_assignment_id"),
        ("progress", "enrollment_id"),
        ("certificates", "enrollment_id"),
    }

    indexes = set(
        (
            await db_session.scalars(
                text(
                    """SELECT indexname FROM pg_indexes WHERE schemaname='public'
                    AND indexname IN ('uq_enrollments_current_occurrence',
                    'uq_enrollments_recurring_assignment','uq_progress_legacy_lesson',
                    'uq_progress_enrollment_lesson','uq_certificates_legacy_user_course',
                    'uq_certificates_enrollment')"""
                )
            )
        ).all()
    )
    assert indexes == {
        "uq_enrollments_current_occurrence",
        "uq_enrollments_recurring_assignment",
        "uq_progress_legacy_lesson",
        "uq_progress_enrollment_lesson",
        "uq_certificates_legacy_user_course",
        "uq_certificates_enrollment",
    }

    permissions = (
        await db_session.execute(
            text(
                """SELECT
                has_function_privilege('lms_app','due_recurring_learning_rules(integer)','EXECUTE'),
                has_function_privilege('lms_recovery','due_recurring_learning_rules(integer)','EXECUTE')"""
            )
        )
    ).one()
    assert permissions == (False, True)

    forced = set(
        (
            await db_session.scalars(
                text(
                    """SELECT relname FROM pg_class WHERE relname IN
                    ('recurring_learning_rules','recurring_learning_assignments')
                    AND relrowsecurity AND relforcerowsecurity"""
                )
            )
        ).all()
    )
    assert forced == {"recurring_learning_rules", "recurring_learning_assignments"}


@pytest.mark.asyncio
async def test_methodologist_recurring_rule_api_is_tenant_scoped(
    client, make_tenant, make_user, make_course, auth_headers
):
    tenant_a = await make_tenant(name="Recurring API A")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    learner_a = await make_user(tenant_a, role="student")
    course_a = await make_course(tenant_a, methodologist_a, status="published", delivery_type="native")
    created = await client.post(
        "/api/v1/learning-cycles",
        headers=auth_headers(methodologist_a),
        json={
            "course_id": str(course_a.id),
            "user_id": str(learner_a.id),
            "cadence_days": 180,
            "due_days": 14,
        },
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["status"] == "draft"

    activated = await client.post(
        f"/api/v1/learning-cycles/{rule['id']}/activate",
        headers=auth_headers(methodologist_a),
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert activated.json()["next_run_at"] is not None

    tenant_b = await make_tenant(name="Recurring API B")
    methodologist_b = await make_user(tenant_b, role="methodologist")
    foreign_list = await client.get("/api/v1/learning-cycles", headers=auth_headers(methodologist_b))
    assert foreign_list.status_code == 200
    assert foreign_list.json() == []


@pytest.mark.asyncio
async def test_materialized_occurrence_is_idempotent_and_isolates_learning_records(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    set_current_tenant,
    monkeypatch,
    auth_headers,
):
    tenant = await make_tenant(name="Recurring materialization")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email=" ")
    course = await make_course(tenant, methodologist, status="published", delivery_type="native")
    release = await ensure_course_release(db_session, course)
    module = await make_module(course)
    lesson = await make_lesson(module)
    quiz = await make_quiz(lesson)
    await set_current_tenant(tenant)

    legacy = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        content_release_id=release.id,
        status="completed",
        source="manual",
        completed_at=datetime.now(UTC) - timedelta(days=30),
    )
    db_session.add(legacy)
    await db_session.flush()
    db_session.add(
        Progress(
            tenant_id=tenant.id,
            user_id=learner.id,
            course_id=course.id,
            lesson_id=lesson.id,
            enrollment_id=None,
            completed=True,
            completion_percent=100,
            percent=100,
        )
    )
    db_session.add(
        QuizAttempt(
            tenant_id=tenant.id,
            user_id=learner.id,
            quiz_id=quiz.id,
            enrollment_id=legacy.id,
            score_percent=100,
            total_points=1,
            earned_points=1,
            passed=True,
            answers=[],
        )
    )
    db_session.add(
        Certificate(
            tenant_id=tenant.id,
            user_id=learner.id,
            course_id=course.id,
            enrollment_id=None,
            certificate_number=f"LEGACY-{uuid4().hex[:12]}",
        )
    )
    rule = RecurringLearningRule(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        cadence_days=180,
        due_days=14,
        status="active",
        next_run_at=datetime.now(UTC),
        created_by=methodologist.id,
    )
    db_session.add(rule)
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(cycle_service, "async_session_factory", lambda: SharedSessionContext())
    monkeypatch.setattr(
        cycle_service,
        "queue_manual_enrollment_notification",
        AsyncMock(return_value=None),
    )
    first = await cycle_service.materialize_rule(rule.id, tenant.id, now=datetime.now(UTC))
    second = await cycle_service.materialize_rule(rule.id, tenant.id, now=datetime.now(UTC))
    assert first["status"] == "materialized"
    assert second["status"] == "skipped"

    occurrence = await db_session.scalar(
        select(RecurringLearningAssignment).where(RecurringLearningAssignment.rule_id == rule.id)
    )
    recurring = await db_session.scalar(select(Enrollment).where(Enrollment.recurring_assignment_id == occurrence.id))
    assert recurring.id != legacy.id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(RecurringLearningAssignment)
            .where(RecurringLearningAssignment.rule_id == rule.id)
        )
        == 1
    )

    assert await get_lesson_progress(db_session, learner.id, lesson.id, tenant.id) is None
    assert await get_user_attempts(db_session, quiz.id, learner.id, tenant.id) == []

    await update_lesson_progress(db_session, learner.id, lesson.id, tenant.id, completed=True)
    cycle_progress = await get_lesson_progress(db_session, learner.id, lesson.id, tenant.id)
    assert cycle_progress.enrollment_id == recurring.id
    cycle_attempt = QuizAttempt(
        tenant_id=tenant.id,
        user_id=learner.id,
        quiz_id=quiz.id,
        enrollment_id=recurring.id,
        score_percent=90,
        total_points=1,
        earned_points=1,
        passed=True,
        answers=[],
    )
    db_session.add(cycle_attempt)
    recurring.status = "completed"
    recurring.completed_at = datetime.now(UTC)
    await db_session.flush()
    assert [item.id for item in await get_user_attempts(db_session, quiz.id, learner.id, tenant.id)] == [
        cycle_attempt.id
    ]

    cycle_certificate = await issue_certificate(
        db_session, learner.id, course.id, tenant.id, enrollment_id=recurring.id
    )
    assert cycle_certificate.enrollment_id == recurring.id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(Certificate)
            .where(
                Certificate.tenant_id == tenant.id,
                Certificate.user_id == learner.id,
                Certificate.course_id == course.id,
            )
        )
        == 2
    )

    now = occurrence.due_at + timedelta(days=1)
    recurring.completed_at = now
    before_learner = await make_user(tenant, role="student")
    overdue_learner = await make_user(tenant, role="student")
    await set_current_tenant(tenant)
    before_rule = RecurringLearningRule(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=before_learner.id,
        cadence_days=180,
        due_days=14,
        status="active",
        created_by=methodologist.id,
    )
    overdue_rule = RecurringLearningRule(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=overdue_learner.id,
        cadence_days=180,
        due_days=14,
        status="active",
        created_by=methodologist.id,
    )
    db_session.add_all([before_rule, overdue_rule])
    await db_session.flush()
    db_session.add_all(
        [
            RecurringLearningAssignment(
                tenant_id=tenant.id,
                rule_id=before_rule.id,
                user_id=before_learner.id,
                course_id=course.id,
                sequence_no=1,
                scheduled_for=now,
                due_at=now + timedelta(days=1),
                effective_due_at=now + timedelta(days=1),
                status="assigned",
            ),
            RecurringLearningAssignment(
                tenant_id=tenant.id,
                rule_id=overdue_rule.id,
                user_id=overdue_learner.id,
                course_id=course.id,
                sequence_no=1,
                scheduled_for=now - timedelta(days=2),
                due_at=now - timedelta(days=1),
                effective_due_at=now - timedelta(days=1),
                status="assigned",
            ),
        ]
    )
    await db_session.flush()
    reporting = await client.get("/api/v1/learning-cycles/occurrences", headers=auth_headers(methodologist))
    assert reporting.status_code == 200, reporting.text
    by_rule = {item["rule_id"]: item for item in reporting.json()}
    assert by_rule[str(before_rule.id)]["status"] == "assigned"
    assert by_rule[str(overdue_rule.id)]["status"] == "overdue"
    assert by_rule[str(rule.id)]["status"] == "completed_late"
    assert by_rule[str(rule.id)]["due_at"] is not None
    assert by_rule[str(rule.id)]["completed_at"] is not None


@pytest.mark.asyncio
async def test_occurrence_history_and_reasoned_deadline_override_are_tenant_scoped(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
    auth_headers,
):
    tenant = await make_tenant(name="Recurring deadline history")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, status="published", delivery_type="native")
    release = await ensure_course_release(db_session, course)
    await set_current_tenant(tenant)
    now = datetime.now(UTC)
    rule = RecurringLearningRule(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        cadence_days=30,
        due_days=7,
        status="active",
        created_by=methodologist.id,
    )
    db_session.add(rule)
    await db_session.flush()
    original_first_due = now - timedelta(days=20)
    original_active_due = now + timedelta(days=7)
    completed = RecurringLearningAssignment(
        tenant_id=tenant.id,
        rule_id=rule.id,
        user_id=learner.id,
        course_id=course.id,
        content_release_id=release.id,
        sequence_no=1,
        scheduled_for=now - timedelta(days=30),
        due_at=original_first_due,
        effective_due_at=original_first_due,
        status="completed",
    )
    active = RecurringLearningAssignment(
        tenant_id=tenant.id,
        rule_id=rule.id,
        user_id=learner.id,
        course_id=course.id,
        content_release_id=release.id,
        sequence_no=2,
        scheduled_for=now,
        due_at=original_active_due,
        effective_due_at=original_active_due,
        status="assigned",
    )
    db_session.add_all([completed, active])
    await db_session.flush()
    completed_enrollment = Enrollment(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        recurring_assignment_id=completed.id,
        content_release_id=release.id,
        status="completed",
        completed_at=now - timedelta(days=10),
        source="recurring",
    )
    enrollment = Enrollment(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        recurring_assignment_id=active.id,
        content_release_id=release.id,
        status="enrolled",
        source="recurring",
    )
    db_session.add_all([completed_enrollment, enrollment])
    await db_session.flush()
    completed.enrollment_id = completed_enrollment.id
    active.enrollment_id = enrollment.id
    await db_session.commit()

    latest = await client.get(
        "/api/v1/learning-cycles/occurrences",
        headers=auth_headers(methodologist),
    )
    assert latest.status_code == 200, latest.text
    assert [item["id"] for item in latest.json() if item["rule_id"] == str(rule.id)] == [str(active.id)]

    history = await client.get(
        "/api/v1/learning-cycles/occurrences?scope=history",
        headers=auth_headers(methodologist),
    )
    assert history.status_code == 200, history.text
    own_history = [item for item in history.json() if item["rule_id"] == str(rule.id)]
    assert [item["sequence_no"] for item in own_history] == [2, 1]

    changed_due = original_active_due + timedelta(days=5)
    changed = await client.post(
        f"/api/v1/learning-cycles/occurrences/course/{active.id}/deadline-override",
        headers=auth_headers(methodologist),
        json={
            "effective_due_at": changed_due.isoformat(),
            "reason": "Подтвержденная командировка сотрудника требует переноса срока",
        },
    )
    assert changed.status_code == 200, changed.text
    assert datetime.fromisoformat(changed.json()["original_due_at"].replace("Z", "+00:00")) == original_active_due
    assert datetime.fromisoformat(changed.json()["effective_due_at"].replace("Z", "+00:00")) == changed_due
    assert datetime.fromisoformat(changed.json()["due_at"].replace("Z", "+00:00")) == changed_due

    await set_current_tenant(tenant)
    await db_session.refresh(active)
    assert active.due_at == original_active_due
    assert active.effective_due_at == changed_due
    events = list(
        (
            await db_session.scalars(
                select(LearningCycleParticipantEvent).where(
                    LearningCycleParticipantEvent.course_occurrence_id == active.id
                )
            )
        ).all()
    )
    assert len(events) == 1
    assert events[0].reason == "Подтвержденная командировка сотрудника требует переноса срока"
    assert events[0].actor_id == methodologist.id

    event_response = await client.get(
        f"/api/v1/learning-cycles/occurrences/course/{active.id}/events",
        headers=auth_headers(methodologist),
    )
    assert event_response.status_code == 200, event_response.text
    assert len(event_response.json()) == 1

    terminal = await client.post(
        f"/api/v1/learning-cycles/occurrences/course/{completed.id}/deadline-override",
        headers=auth_headers(methodologist),
        json={
            "effective_due_at": (original_first_due + timedelta(days=1)).isoformat(),
            "reason": "Этот перенос не должен примениться к завершенному циклу",
        },
    )
    assert terminal.status_code == 409

    foreign_tenant = await make_tenant(name="Recurring deadline foreign")
    foreign_methodologist = await make_user(foreign_tenant, role="methodologist")
    foreign = await client.post(
        f"/api/v1/learning-cycles/occurrences/course/{active.id}/deadline-override",
        headers=auth_headers(foreign_methodologist),
        json={
            "effective_due_at": (changed_due + timedelta(days=1)).isoformat(),
            "reason": "Чужой кабинет не может изменять срок этого сотрудника",
        },
    )
    assert foreign.status_code == 404
