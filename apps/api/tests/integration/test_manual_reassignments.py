"""Public API regressions for immutable manual reassignment occurrences."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def _manual_enrollment(db_session, *, tenant, learner, course, status="enrolled"):
    from app.models.enrollment import Enrollment

    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        status=status,
        source="manual",
        completed_at=datetime.now(UTC) if status == "completed" else None,
    )
    db_session.add(enrollment)
    await db_session.flush()
    return enrollment


async def test_methodologist_reassignment_creates_new_occurrence_and_preserves_completed_history(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Repeat tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Repeatable", status="published")
    predecessor = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="completed"
    )

    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={"user_id": str(learner.id), "previous_enrollment_id": str(predecessor.id), "reason": "annual refresher"},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["previous_enrollment_id"] == str(predecessor.id)
    assert body["enrollment"]["id"] != str(predecessor.id)
    assert body["enrollment"]["status"] == "enrolled"
    assert body["predecessor_status"] == "completed"
    await db_session.refresh(predecessor)
    assert predecessor.status == "completed"
    assert predecessor.completed_at is not None
    current = await client.get(
        f"/api/v1/courses/{course.id}/enrollments",
        headers=auth_headers(methodologist),
    )
    assert current.status_code == 200, current.text
    assert [item["id"] for item in current.json()] == [body["enrollment"]["id"]]


async def test_methodologist_reassignment_supersedes_open_manual_predecessor_and_is_tenant_safe(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant_a = await make_tenant(name="Repeat tenant A")
    tenant_b = await make_tenant(name="Repeat tenant B")
    owner_a = await make_user(tenant_a, role="methodologist")
    owner_b = await make_user(tenant_b, role="methodologist")
    learner_a = await make_user(tenant_a, role="student")
    course_a = await make_course(tenant_a, owner_a, title="A course", status="published")
    predecessor = await _manual_enrollment(db_session, tenant=tenant_a, learner=learner_a, course=course_a)
    # The foreign request is expected to roll its transaction back.  Persist the
    # fixture savepoint first so that rollback cannot erase the subsequent
    # same-tenant actor and turn the success assertion into an unrelated 401.
    await db_session.commit()

    foreign = await client.post(
        f"/api/v1/courses/{course_a.id}/reassignments",
        json={"user_id": str(learner_a.id), "previous_enrollment_id": str(predecessor.id), "reason": "foreign retry"},
        headers=auth_headers(owner_b),
    )
    assert foreign.status_code == 404

    response = await client.post(
        f"/api/v1/courses/{course_a.id}/reassignments",
        json={
            "user_id": str(learner_a.id),
            "previous_enrollment_id": str(predecessor.id),
            "reason": "corrective training",
        },
        headers=auth_headers(owner_a),
    )
    assert response.status_code == 201, response.text
    await db_session.refresh(predecessor)
    assert predecessor.status == "superseded"
    assert response.json()["enrollment"]["previous_enrollment_id"] == str(predecessor.id)


async def test_reassignment_reissues_email_delivery_and_carries_relative_timing_policy(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    from sqlalchemy import select

    from app.models.course_assignment_notification import CourseAssignmentNotificationOutbox
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy

    tenant = await make_tenant(name="Repeat email delivery tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Repeat email delivery", status="published")
    predecessor = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="completed"
    )
    policy_origin = datetime.now(UTC) - timedelta(days=1)
    db_session.add(
        EnrollmentAccessPolicy(
            tenant_id=tenant.id,
            enrollment_id=predecessor.id,
            user_id=learner.id,
            delivery_mode="email",
            completion_window_minutes=90,
            due_at=policy_origin + timedelta(days=14),
            due_window_minutes=14 * 24 * 60,
            created_at=policy_origin,
        )
    )
    await db_session.flush()

    extended_due_at = datetime.now(UTC) + timedelta(days=3)
    extension = await client.post(
        f"/api/v1/courses/enrollments/{predecessor.id}/access-policy/extend",
        json={"due_at": extended_due_at.isoformat(), "reason": "new deadline policy"},
        headers=auth_headers(methodologist),
    )
    assert extension.status_code == 200, extension.text

    before = datetime.now(UTC)
    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={
            "user_id": str(learner.id),
            "previous_enrollment_id": str(predecessor.id),
            "reason": "repeat with fresh email delivery",
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["delivery_mode"] == "email"
    assert body["personal_access"] is None
    current_id = UUID(body["enrollment"]["id"])
    policy = await db_session.scalar(
        select(EnrollmentAccessPolicy).where(EnrollmentAccessPolicy.enrollment_id == current_id)
    )
    assert policy is not None
    assert policy.delivery_mode == "email"
    assert policy.completion_window_minutes == 90
    assert before + timedelta(days=2, hours=23) <= policy.due_at <= datetime.now(UTC) + timedelta(days=3, minutes=1)
    notification = await db_session.scalar(
        select(CourseAssignmentNotificationOutbox).where(
            CourseAssignmentNotificationOutbox.enrollment_id == current_id
        )
    )
    assert notification is not None


async def test_reassignment_reissues_personal_link_and_returns_new_one_time_secret(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    from sqlalchemy import select

    from app.models.assignment_access import AssignmentAccessCredential
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy

    tenant = await make_tenant(name="Repeat personal delivery tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Repeat personal delivery", status="published")
    predecessor = await _manual_enrollment(db_session, tenant=tenant, learner=learner, course=course)
    policy_origin = datetime.now(UTC) - timedelta(hours=6)
    predecessor_policy = EnrollmentAccessPolicy(
        tenant_id=tenant.id,
        enrollment_id=predecessor.id,
        user_id=learner.id,
        delivery_mode="personal_link",
        link_expires_at=policy_origin + timedelta(days=7),
        link_validity_minutes=7 * 24 * 60,
        completion_window_minutes=120,
        due_at=policy_origin + timedelta(days=10),
        due_window_minutes=10 * 24 * 60,
        created_at=policy_origin,
    )
    db_session.add(predecessor_policy)
    await db_session.flush()

    before = datetime.now(UTC)
    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={
            "user_id": str(learner.id),
            "previous_enrollment_id": str(predecessor.id),
            "reason": "repeat with a fresh protected link",
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["delivery_mode"] == "personal_link"
    assert body["personal_access"]["access_url"].startswith("https://")
    assert len(body["personal_access"]["temporary_pin"]) == 6
    current_id = UUID(body["enrollment"]["id"])
    policy = await db_session.scalar(
        select(EnrollmentAccessPolicy).where(EnrollmentAccessPolicy.enrollment_id == current_id)
    )
    assert policy is not None
    assert policy.delivery_mode == "personal_link"
    assert policy.completion_window_minutes == 120
    assert (
        before + timedelta(days=6, hours=23)
        <= policy.link_expires_at
        <= datetime.now(UTC) + timedelta(days=7, minutes=1)
    )
    active = await db_session.scalar(
        select(AssignmentAccessCredential).where(
            AssignmentAccessCredential.enrollment_id == current_id,
            AssignmentAccessCredential.revoked_at.is_(None),
        )
    )
    assert active is not None
    await db_session.refresh(predecessor_policy)
    assert predecessor_policy.revoked_at is not None


async def test_reassignment_rejects_an_unrecoverable_expired_deadline_policy(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    from sqlalchemy import func, select

    from app.models.enrollment import Enrollment
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy

    tenant = await make_tenant(name="Expired repeat policy tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Expired repeat policy", status="published")
    predecessor = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="completed"
    )
    db_session.add(
        EnrollmentAccessPolicy(
            tenant_id=tenant.id,
            enrollment_id=predecessor.id,
            user_id=learner.id,
            delivery_mode="email",
            due_at=datetime.now(UTC) - timedelta(days=1),
            due_window_minutes=None,
        )
    )
    await db_session.flush()

    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={
            "user_id": str(learner.id),
            "previous_enrollment_id": str(predecessor.id),
            "reason": "must not drop an expired policy",
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Assignment deadline policy must be extended before reassignment"
    assert await db_session.scalar(
        select(func.count(Enrollment.id)).where(Enrollment.previous_enrollment_id == predecessor.id)
    ) == 0


async def test_reassignment_resets_quiz_attempt_scope_without_erasing_predecessor_attempts(
    client, db_session, make_tenant, make_user, make_course, make_module, make_lesson, make_quiz, auth_headers
):
    from sqlalchemy import func, select

    from app.modules.quizzes.models import QuizAttempt

    tenant = await make_tenant(name="Attempt scope tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Attempt scope", status="published")
    lesson = await make_lesson(await make_module(course, title="Module"), title="Lesson")
    quiz = await make_quiz(lesson, title="Assessment", attempt_limit=1)
    predecessor = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="completed"
    )
    db_session.add(
        QuizAttempt(
            tenant_id=tenant.id,
            user_id=learner.id,
            quiz_id=quiz.id,
            enrollment_id=predecessor.id,
            score_percent=0,
            total_points=1,
            earned_points=0,
            passed=False,
            answers=[],
        )
    )
    await db_session.flush()

    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={
            "user_id": str(learner.id),
            "previous_enrollment_id": str(predecessor.id),
            "reason": "new assessed occurrence",
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 201, response.text
    new_enrollment_id = response.json()["enrollment"]["id"]
    assert await db_session.scalar(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.enrollment_id == predecessor.id)
    ) == 1
    assert await db_session.scalar(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.enrollment_id == new_enrollment_id)
    ) == 0


async def test_reassignment_starts_clean_lesson_progress_and_learner_dashboard_occurrence(
    client, db_session, make_tenant, make_user, make_course, make_module, make_lesson, auth_headers
):
    from sqlalchemy import select

    from app.models.progress import Progress
    from app.modules.progress.service import get_course_progress, update_lesson_progress
    from app.modules.student.service import get_student_dashboard

    tenant = await make_tenant(name="Progress scope tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Progress scope", status="published")
    lesson = await make_lesson(await make_module(course, title="Module"), title="Lesson")
    predecessor = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="completed"
    )
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
    await db_session.flush()

    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={
            "user_id": str(learner.id),
            "previous_enrollment_id": str(predecessor.id),
            "reason": "repeat from a clean lesson state",
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 201, response.text
    current_id = response.json()["enrollment"]["id"]

    before = await get_course_progress(db_session, learner.id, course.id, tenant.id)
    assert before["completed_lessons"] == 0
    dashboard = await get_student_dashboard(db_session, learner.id, tenant.id)
    assert [str(item["enrollment_id"]) for item in dashboard["enrolled_courses"]] == [current_id]
    assert dashboard["enrolled_courses"][0]["progress_percent"] == 0

    await update_lesson_progress(db_session, learner.id, lesson.id, tenant.id, completed=True)
    scoped = await db_session.scalar(
        select(Progress).where(Progress.enrollment_id == UUID(current_id), Progress.lesson_id == lesson.id)
    )
    assert scoped is not None
    assert scoped.completed is True


async def test_reassignment_rejects_rule_driven_source_and_non_methodologist(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Rule tenant")
    methodologist = await make_user(tenant, role="methodologist")
    admin = await make_user(tenant, role="admin")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="Rule course", status="published")
    forbidden = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={"user_id": str(learner.id), "previous_enrollment_id": str(uuid4()), "reason": "not allowed"},
        headers=auth_headers(admin),
    )
    assert forbidden.status_code == 403

    rule_enrollment = await _manual_enrollment(db_session, tenant=tenant, learner=learner, course=course)
    rule_enrollment.source = "position"
    await db_session.flush()
    response = await client.post(
        f"/api/v1/courses/{course.id}/reassignments",
        json={
            "user_id": str(learner.id),
            "previous_enrollment_id": str(rule_enrollment.id),
            "reason": "cannot override rule",
        },
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 409


async def test_training_log_current_default_excludes_retained_history_and_history_is_explicit(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="History tenant")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    course = await make_course(tenant, methodologist, title="History course", status="published")
    predecessor = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="completed"
    )
    current = await _manual_enrollment(db_session, tenant=tenant, learner=learner, course=course)
    current.previous_enrollment_id = predecessor.id
    current.reassignment_reason = "knowledge refresh"
    current.reassigned_by = methodologist.id
    current.reassigned_at = datetime.now(UTC)
    cancelled = await _manual_enrollment(db_session, tenant=tenant, learner=learner, course=course, status="cancelled")
    superseded = await _manual_enrollment(
        db_session, tenant=tenant, learner=learner, course=course, status="superseded"
    )

    default = await client.get("/api/v1/admin/training-log", headers=auth_headers(methodologist))
    assert default.status_code == 200, default.text
    assert [item["enrollment_id"] for item in default.json()["items"]] == [str(current.id)]

    history = await client.get("/api/v1/admin/training-log?history=true", headers=auth_headers(methodologist))
    assert history.status_code == 200, history.text
    assert {item["enrollment_id"] for item in history.json()["items"]} == {
        str(predecessor.id), str(current.id), str(cancelled.id), str(superseded.id)
    }
    assert {item["computed_status"] for item in history.json()["items"]} >= {"cancelled", "superseded"}
    summary = await client.get("/api/v1/admin/training-log/summary", headers=auth_headers(methodologist))
    assert summary.status_code == 200, summary.text
    assert summary.json()["total"] == 1
    assert summary.json()["cancelled_history"] == 1
    assert summary.json()["superseded_history"] == 1

    summary_with_history = await client.get(
        "/api/v1/admin/training-log/summary?history=true", headers=auth_headers(methodologist)
    )
    assert summary_with_history.status_code == 200, summary_with_history.text
    assert summary_with_history.json()["total"] == 1
    assert summary_with_history.json()["assigned"] == 1
    assert summary_with_history.json()["completed"] == 0

    dashboard = await client.get("/api/v1/enrollments/stats", headers=auth_headers(methodologist))
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json() == {"total": 1, "completed": 0}
