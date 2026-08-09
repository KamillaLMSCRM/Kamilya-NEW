from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models.enrollment import Enrollment
from app.models.progress import Progress
from app.modules.certificates.models import Certificate
from app.modules.certificates.service import issue_certificate
from app.modules.learning_cycles import service as cycle_service
from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
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
                    AND indexname IN ('uq_enrollments_legacy_active',
                    'uq_enrollments_recurring_assignment','uq_progress_legacy_lesson',
                    'uq_progress_enrollment_lesson','uq_certificates_legacy_user_course',
                    'uq_certificates_enrollment')"""
                )
            )
        ).all()
    )
    assert len(indexes) == 6

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
    module = await make_module(course)
    lesson = await make_lesson(module)
    quiz = await make_quiz(lesson)
    await set_current_tenant(tenant)

    legacy = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
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

    now = datetime.now(UTC)
    occurrence.due_at = now - timedelta(days=1)
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
                scheduled_for=now,
                due_at=now + timedelta(days=1),
                status="assigned",
            ),
            RecurringLearningAssignment(
                tenant_id=tenant.id,
                rule_id=overdue_rule.id,
                user_id=overdue_learner.id,
                course_id=course.id,
                scheduled_for=now - timedelta(days=2),
                due_at=now - timedelta(days=1),
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
