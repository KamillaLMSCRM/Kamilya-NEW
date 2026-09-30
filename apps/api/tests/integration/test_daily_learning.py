"""Daily-learning assembled read chain; synthetic rows, outer rollback only."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models.enrollment import Enrollment
from app.models.enrollment_access_policy import EnrollmentAccessPolicy
from app.models.progress import Progress
from app.modules.courses.release_service import ensure_course_release
from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
from app.modules.quizzes.models import QuizAttempt
from app.modules.student.service import get_student_dashboard
from app.modules.training_log.repository import count_training_log, list_training_log
from app.modules.training_log.schemas import TrainingLogFilter

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def daily_learning(
    client, db_session, make_tenant, make_user, make_course, make_module, make_lesson,
    make_quiz, set_current_tenant,
):
    # Bootstrap the real app/model registry through the canonical client fixture
    # before flushing occurrence FKs; isolated-file collection must also work.
    tenant = await make_tenant(name="Daily learning A", slug="daily-learning-a")
    foreign = await make_tenant(name="Daily learning B", slug="daily-learning-b")
    owner = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    peer = await make_user(tenant, role="student")
    outsider = await make_user(foreign, role="student")
    course = await make_course(tenant, owner, title="Daily learning course", status="published")
    resolved_course = await make_course(tenant, owner, title="Resolved assessment", status="published")
    foreign_course = await make_course(foreign, outsider, title="Foreign private course", status="published")
    module = await make_module(course)
    first = await make_lesson(module, title="First lesson", order_index=0)
    last = await make_lesson(module, title="Resume here", order_index=1)
    quiz = await make_quiz(first, attempt_limit=2)
    other_quiz = await make_quiz(last, attempt_limit=2)
    resolved_quiz = await make_quiz(await make_lesson(await make_module(resolved_course)), attempt_limit=1)
    foreign_quiz = await make_quiz(await make_lesson(await make_module(foreign_course)), attempt_limit=1)
    releases = {}
    for target in (course, resolved_course, foreign_course):
        await set_current_tenant(target.tenant_id)
        releases[target.id] = await ensure_course_release(db_session, target)
    stamp = datetime(2026, 10, 5, 12, tzinfo=UTC)

    async def enrollment(user, target, *, source="manual", enrolled_at=None, **values):
        await set_current_tenant(user.tenant_id)
        item = Enrollment(
            id=uuid4(), tenant_id=user.tenant_id, user_id=user.id, course_id=target.id,
            content_release_id=releases[target.id].id,
            status="enrolled", source=source, enrolled_at=enrolled_at or stamp, **values,
        )
        db_session.add(item)
        await db_session.flush()
        return item

    await set_current_tenant(tenant)
    history = Enrollment(
        id=uuid4(), tenant_id=tenant.id, user_id=learner.id, course_id=course.id,
        status="completed", source="manual", enrolled_at=stamp - timedelta(days=30),
        content_release_id=releases[course.id].id,
        completed_at=stamp - timedelta(days=20),
    )
    db_session.add(history)
    await db_session.flush()
    # The current-occurrence unique index allows a separate recurring grant,
    # not two non-recurring current grants for the same learner/course.
    older_due = stamp - timedelta(days=5)
    rule = RecurringLearningRule(
        tenant_id=tenant.id, course_id=course.id, user_id=learner.id,
        cadence_days=365, due_days=7, status="active", created_by=owner.id,
    )
    db_session.add(rule)
    await db_session.flush()
    occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id, rule_id=rule.id, user_id=learner.id, course_id=course.id,
        sequence_no=1, scheduled_for=stamp - timedelta(days=10),
        content_release_id=releases[course.id].id,
        due_at=older_due - timedelta(days=1), effective_due_at=older_due, status="assigned",
    )
    db_session.add(occurrence)
    await db_session.flush()
    older = await enrollment(
        learner, course, source="recurring", enrolled_at=stamp - timedelta(days=10),
        recurring_assignment_id=occurrence.id,
    )
    occurrence.enrollment_id = older.id
    await db_session.flush()
    current = await enrollment(
        learner, course, previous_enrollment_id=history.id,
        reassignment_reason="Synthetic daily-learning acceptance",
        reassigned_by=owner.id, reassigned_at=stamp,
    )
    resolved = await enrollment(learner, resolved_course)
    foreign_enrollment = await enrollment(outsider, foreign_course)
    await set_current_tenant(tenant)
    db_session.add(EnrollmentAccessPolicy(
        tenant_id=tenant.id, user_id=learner.id, enrollment_id=current.id, due_at=stamp,
    ))
    for item, test, passed in (
        (older, quiz, False), (older, other_quiz, False),
        (current, quiz, False), (current, quiz, False),
        (resolved, resolved_quiz, False), (resolved, resolved_quiz, True),
    ):
        db_session.add(QuizAttempt(
            tenant_id=tenant.id, user_id=learner.id, enrollment_id=item.id,
            quiz_id=test.id, passed=passed, score_percent=100 if passed else 0,
        ))
    # Old NULL-scoped progress must not contaminate the repeated occurrence.
    for lesson in (first, last):
        db_session.add(Progress(
            tenant_id=tenant.id, user_id=learner.id, course_id=course.id,
            lesson_id=lesson.id, enrollment_id=None, completed=True,
            percent=100, completion_percent=100,
        ))
    db_session.add(Progress(
        tenant_id=tenant.id, user_id=learner.id, course_id=course.id,
        lesson_id=last.id, enrollment_id=current.id, completed=False,
        percent=20, completion_percent=20, last_accessed_at=stamp,
    ))
    await db_session.flush()
    await set_current_tenant(foreign)
    db_session.add(QuizAttempt(
        tenant_id=foreign.id, user_id=outsider.id, enrollment_id=foreign_enrollment.id,
        quiz_id=foreign_quiz.id, passed=False,
    ))
    await db_session.flush()
    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    role = (await db_session.execute(text(
        "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
    ))).one()
    assert tuple(role) == ("lms_app", False, False)
    await set_current_tenant(tenant)
    yield SimpleNamespace(
        tenant=tenant, foreign=foreign, owner=owner, learner=learner, peer=peer,
        outsider=outsider, course=course, foreign_course=foreign_course,
        older=older, current=current, resolved=resolved, history=history,
        foreign_enrollment=foreign_enrollment, due=stamp, older_due=older_due, lesson=last,
    )


@pytest.mark.parametrize("assessment,expected_count", [("failed", 2), ("exhausted", 1)])
async def test_assessment_list_summary_csv_share_exact_occurrence_filter(
    daily_learning, client, auth_headers, assessment, expected_count,
):
    data = daily_learning
    expected = {str(data.current.id)}
    if assessment == "failed":
        expected.add(str(data.older.id))
    headers = auth_headers(data.owner)
    params = {"assessment_status": assessment}
    page = await client.get("/api/v1/admin/training-log", params=params, headers=headers)
    summary = await client.get("/api/v1/admin/training-log/summary", params=params, headers=headers)
    exported = await client.get(
        "/api/v1/admin/training-log", params={**params, "format": "csv", "lang": "en"}, headers=headers,
    )
    assert page.status_code == summary.status_code == exported.status_code == 200
    assert page.json()["total"] == summary.json()["total"] == expected_count
    rows = page.json()["items"]
    assert {item["enrollment_id"] for item in rows} == expected
    assert all(item["user_id"] == str(data.learner.id) for item in rows)
    csv_rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))
    assert len(csv_rows) == expected_count
    assert {item["Course"] for item in csv_rows} == {data.course.title}
    dates = {data.due.strftime("%d.%m.%Y %H:%M")}
    if assessment == "failed":
        dates.add(data.older_due.strftime("%d.%m.%Y %H:%M"))
    assert {item["Assignment due at"] for item in csv_rows} == dates
    paginated = await client.get(
        "/api/v1/admin/training-log", params={**params, "limit": 1}, headers=headers,
    )
    assert paginated.status_code == 200
    assert paginated.json()["total"] == expected_count
    assert len(paginated.json()["items"]) == 1
    foreign = await client.get(
        "/api/v1/admin/training-log",
        params={**params, "enrollment_id": str(data.foreign_enrollment.id)}, headers=headers,
    )
    assert foreign.status_code == 200
    assert foreign.json()["total"] == 0


async def test_learner_deadline_resume_and_restricted_identity_are_rls_safe(
    daily_learning, client, db_session, auth_headers,
):
    data = daily_learning
    response = await client.get("/api/v1/student/dashboard", headers=auth_headers(data.learner))
    assert response.status_code == 200
    courses = {item["enrollment_id"]: item for item in response.json()["enrolled_courses"]}
    assert set(courses) == {str(data.current.id), str(data.older.id), str(data.resolved.id)}
    current = courses[str(data.current.id)]
    assert current["can_resume"] is True
    assert current["resume_href"] == f"/courses/{data.course.id}?lessonId={data.lesson.id}"
    assert current["progress_percent"] == 0
    assert current["assignment_source"] == "manual"
    assert datetime.fromisoformat(current["assignment_due_at"]) == data.due
    assert courses[str(data.older.id)]["can_resume"] is False
    assert courses[str(data.older.id)]["resume_href"] is None
    assert courses[str(data.older.id)]["assignment_source"] == "recurring"
    assert datetime.fromisoformat(courses[str(data.older.id)]["assignment_due_at"]) == data.older_due
    for enrollment, resumable in ((data.current, True), (data.older, False)):
        scoped = await get_student_dashboard(
            db_session, data.learner.id, data.tenant.id, enrollment_id=enrollment.id,
        )
        assert len(scoped["enrolled_courses"]) == 1
        item = scoped["enrolled_courses"][0]
        assert item["enrollment_id"] == enrollment.id
        assert item["can_resume"] is resumable
        if not resumable:
            assert item["resume_href"] is None
    for user_id, tenant_id, enrollment_id in (
        (data.peer.id, data.tenant.id, data.current.id),
        (data.learner.id, data.tenant.id, data.foreign_enrollment.id),
        (data.outsider.id, data.foreign.id, data.foreign_enrollment.id),
    ):
        denied = await get_student_dashboard(db_session, user_id, tenant_id, enrollment_id=enrollment_id)
        assert denied["enrolled_courses"] == []
    assert await count_training_log(db_session, data.foreign.id, TrainingLogFilter()) == 0
    assert await list_training_log(db_session, data.foreign.id, TrainingLogFilter()) == []
    assert await db_session.scalar(text(
        "SELECT count(*) FROM enrollments WHERE tenant_id=:tenant"
    ), {"tenant": data.foreign.id}) == 0
    tables = ["enrollments", "courses", "progress", "quizzes", "quiz_attempts", "enrollment_access_policies"]
    forced = (await db_session.execute(text(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
        "WHERE relnamespace='public'::regnamespace AND relname=ANY(:tables)"
    ), {"tables": tables})).all()
    assert len(forced) == len(tables)
    assert all(row.relrowsecurity and row.relforcerowsecurity for row in forced)
