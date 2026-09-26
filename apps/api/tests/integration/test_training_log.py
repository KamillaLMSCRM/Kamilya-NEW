"""Integration tests for /api/v1/admin/training-log.

Covers:
- happy path: tenant admin sees rows of his own tenant
- tenant isolation: Tenant A cannot see Tenant B's rows (404 from RBAC, not 500)
- filters: course_id, delivery_type, status=completed
- CSV export: ?format=csv returns text/csv with UTF-8 BOM
- pagination: limit/offset
- auth: 401 for unauthenticated, 403 for non-admin role (student)
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


async def _login(client, user, password: str = "Password123!") -> str:
    """Helper to obtain a JWT for the given user."""
    # The login endpoint accepts email+password (separate from magic-link).
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _enroll(
    db,
    user,
    course,
    *,
    status="enrolled",
    source="manual",
    recurring_assignment_id=None,
    completed_at=None,
):
    """Insert an enrollment row directly (faster than HTTP-driven flow)."""
    from app.models.enrollment import Enrollment

    e = Enrollment(
        id=uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        course_id=course.id,
        status=status,
        enrolled_at=datetime.now(UTC),
        source=source,
        recurring_assignment_id=recurring_assignment_id,
        completed_at=completed_at,
    )
    db.add(e)
    await db.flush()
    return e


@pytest.mark.asyncio
async def test_training_log_requires_auth(client):
    resp = await client.get("/api/v1/admin/training-log")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_training_log_student_forbidden(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme")
    student = await make_user(tenant, role="student", email="stu@acme.example")
    course = await make_course(tenant, student, title="Intro")
    await _enroll(db_session, student, course)
    token = await _login(client, student)

    resp = await client.get(
        "/api/v1/admin/training-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_training_log_happy_path(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme")
    admin = await make_user(tenant, role="methodologist", email="admin@acme.example")
    student = await make_user(tenant, role="student", email="stu@acme.example")
    course = await make_course(tenant, admin, title="Intro")
    await _enroll(db_session, student, course)

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "total" in body
    assert body["total"] == 1
    row = body["items"][0]
    assert row["course_title"] == "Intro"
    assert row["delivery_type"] == "native"
    assert row["enrollment_status"] == "enrolled"
    assert row["progress_percent"] == 0


@pytest.mark.asyncio
async def test_training_log_exact_enrollment_projection_is_tenant_local(
    client, db_session, make_tenant, make_user, make_course, set_current_tenant
):
    from app.modules.training_log.repository import list_training_log_by_enrollment_ids

    tenant_a = await make_tenant(name="Projection A", slug="projection-a")
    tenant_b = await make_tenant(name="Projection B", slug="projection-b")
    owner_a = await make_user(tenant_a, role="methodologist", email="owner-a@projection.example")
    owner_b = await make_user(tenant_b, role="methodologist", email="owner-b@projection.example")
    learner_a = await make_user(tenant_a, role="student", email="learner-a@projection.example")
    learner_b = await make_user(tenant_b, role="student", email="learner-b@projection.example")
    course_a = await make_course(tenant_a, owner_a, title="Projection course A")
    course_b = await make_course(tenant_b, owner_b, title="Projection course B")
    await set_current_tenant(tenant_a)
    enrollment_a = await _enroll(db_session, learner_a, course_a)
    await set_current_tenant(tenant_b)
    enrollment_b = await _enroll(db_session, learner_b, course_b)

    await set_current_tenant(tenant_a)
    rows = await list_training_log_by_enrollment_ids(
        db_session,
        tenant_a.id,
        [enrollment_a.id, enrollment_b.id],
    )

    assert set(rows) == {enrollment_a.id}
    assert rows[enrollment_a.id]["progress_percent"] == 0
    assert await list_training_log_by_enrollment_ids(db_session, tenant_a.id, []) == {}


@pytest.mark.asyncio
async def test_tenant_admin_can_read_and_export_training_report(
    client, db_session, make_tenant, make_user, make_course
):
    tenant = await make_tenant(name="Admin report", slug="admin-report")
    admin = await make_user(tenant, role="admin", email="viewer@admin-report.example")
    learner = await make_user(tenant, role="student", email="learner@admin-report.example")
    course = await make_course(tenant, admin, title="Required training")
    await _enroll(db_session, learner, course)
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    page = await client.get("/api/v1/admin/training-log", headers=headers)
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1

    exported = await client.get("/api/v1/admin/training-log?format=csv", headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "Required training" in exported.text


@pytest.mark.asyncio
async def test_training_log_tenant_isolation(client, db_session, make_tenant, make_user, make_course):
    tenant_a = await make_tenant(name="AcmeA", slug="acmea")
    tenant_b = await make_tenant(name="AcmeB", slug="acmeb")
    admin_b = await make_user(tenant_b, role="methodologist", email="admin@b.example")
    student_a = await make_user(tenant_a, role="student", email="stu@a.example")
    course_a = await make_course(tenant_a, admin_b, title="CourseA")
    await _enroll(db_session, student_a, course_a)

    # Tenant B admin must NOT see Tenant A rows.
    token_b = await _login(client, admin_b)
    resp = await client.get(
        "/api/v1/admin/training-log",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_training_log_filter_by_completed_status(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme-c")
    admin = await make_user(tenant, role="methodologist", email="admin@c.example")
    student = await make_user(tenant, role="student", email="stu@c.example")
    course = await make_course(tenant, admin, title="C1")
    enrollment = await _enroll(db_session, student, course)

    # Mark it completed
    enrollment.status = "completed"
    enrollment.completed_at = datetime.now(UTC)
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?status=completed",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["progress_percent"] == 100
    assert body["items"][0]["completed_at"] is not None


@pytest.mark.asyncio
async def test_training_log_filter_by_delivery_type_scorm(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme-s")
    admin = await make_user(tenant, role="methodologist", email="admin@s.example")
    student = await make_user(tenant, role="student", email="stu@s.example")
    course = await make_course(tenant, admin, title="ScormCourse", delivery_type="scorm")
    await _enroll(db_session, student, course)

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?delivery_type=scorm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["delivery_type"] == "scorm"


@pytest.mark.asyncio
async def test_training_log_csv_export(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme-x")
    admin = await make_user(tenant, role="methodologist", email="admin@x.example")
    student = await make_user(tenant, role="student", email="stu@x.example")
    course = await make_course(tenant, admin, title="X1")
    await _enroll(db_session, student, course)

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?format=csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.content
    # UTF-8 BOM at the start so Excel opens as UTF-8.
    assert body[:3] == b"\xef\xbb\xbf"
    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["Курс"] == "X1"
    assert "user_id" not in rows[0]
    assert rows[0]["Статус"] == "Назначен"


@pytest.mark.asyncio
async def test_training_log_search_and_csv_share_tenant_scoped_filter(
    client, db_session, make_tenant, make_user, make_course
):
    """A name/email/personnel-number search must narrow both table and CSV."""
    tenant = await make_tenant(name="Acme", slug="acme-search")
    admin = await make_user(tenant, role="methodologist", email="admin@search.example")
    matching = await make_user(
        tenant,
        role="student",
        email="qa.ux@acme.example",
        first_name="QA",
        last_name="UX",
    )
    matching.personnel_number = "QA-UX-20260723-001"
    non_matching = await make_user(
        tenant,
        role="student",
        email="other@acme.example",
        first_name="Other",
        last_name="Employee",
    )
    course = await make_course(tenant, admin, title="Search course")
    await _enroll(db_session, matching, course)
    await _enroll(db_session, non_matching, course)
    await db_session.flush()

    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}
    for search in ("QA", "qa.ux@acme.example", "QA-UX-20260723-001"):
        page = await client.get(
            "/api/v1/admin/training-log",
            params={"search": search},
            headers=headers,
        )
        assert page.status_code == 200, page.text
        assert page.headers["cache-control"] == "no-store"
        assert page.json()["total"] == 1
        assert page.json()["items"][0]["user_id"] == str(matching.id)

    export = await client.get(
        "/api/v1/admin/training-log",
        params={"search": "QA-UX-20260723-001", "format": "csv"},
        headers=headers,
    )
    rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 1
    assert rows[0]["Табельный номер"] == "QA-UX-20260723-001"


@pytest.mark.asyncio
async def test_training_log_summary_matches_filters_and_fresh_enrollment_state(
    client, db_session, make_tenant, make_user, make_course
):
    """The summary is filtered like the table and must not retain stale status counts."""
    tenant = await make_tenant(name="Acme", slug="acme-summary")
    admin = await make_user(tenant, role="methodologist", email="admin@summary.example")
    student = await make_user(tenant, role="student", email="student@summary.example")
    course = await make_course(tenant, admin, title="Summary course")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    before = await client.get("/api/v1/admin/training-log/summary", headers=headers)
    assert before.status_code == 200
    assert before.headers["cache-control"] == "no-store"
    assert before.json() == {
        "total": 0,
        "assigned": 0,
        "in_progress": 0,
        "completed": 0,
        "overdue": 0,
        "failed_current": 0,
        "exhausted_attempts": 0,
        "reassigned": 0,
        "cancelled_history": 0,
        "superseded_history": 0,
    }

    enrollment = await _enroll(db_session, student, course)
    after_assignment = await client.get(
        "/api/v1/admin/training-log/summary?course_id=" + str(course.id), headers=headers
    )
    table_after_assignment = await client.get("/api/v1/admin/training-log?course_id=" + str(course.id), headers=headers)
    assert after_assignment.json() == {
        "total": 1,
        "assigned": 1,
        "in_progress": 0,
        "completed": 0,
        "overdue": 0,
        "failed_current": 0,
        "exhausted_attempts": 0,
        "reassigned": 0,
        "cancelled_history": 0,
        "superseded_history": 0,
    }
    assert table_after_assignment.json()["total"] == after_assignment.json()["total"]

    enrollment.status = "completed"
    enrollment.completed_at = datetime.now(UTC)
    await db_session.flush()
    after_completion = await client.get(
        "/api/v1/admin/training-log/summary?course_id=" + str(course.id), headers=headers
    )
    table_after_completion = await client.get("/api/v1/admin/training-log?course_id=" + str(course.id), headers=headers)
    assert after_completion.json() == {
        "total": 1,
        "assigned": 0,
        "in_progress": 0,
        "completed": 1,
        "overdue": 0,
        "failed_current": 0,
        "exhausted_attempts": 0,
        "reassigned": 0,
        "cancelled_history": 0,
        "superseded_history": 0,
    }
    assert table_after_completion.json()["total"] == after_completion.json()["total"]


@pytest.mark.asyncio
async def test_training_log_pagination(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme-p")
    admin = await make_user(tenant, role="methodologist", email="admin@p.example")
    course = await make_course(tenant, admin, title="P1")
    # 5 enrollments, different students
    for i in range(5):
        s = await make_user(tenant, role="student", email=f"stu{i}@p.example")
        await _enroll(db_session, s, course)

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?limit=2&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2

    resp2 = await client.get(
        "/api/v1/admin/training-log?limit=2&offset=4",
        headers={"Authorization": f"Bearer {token}"},
    )
    body2 = resp2.json()
    assert len(body2["items"]) == 1  # last page has only one row


@pytest.mark.asyncio
async def test_training_log_superadmin_no_tenant_returns_empty(client, db_session, make_superadmin):
    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    resp = await client.get(
        "/api/v1/admin/training-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Superadmin role is allowed in our role tuple, but tenant_id=None,
    # so the endpoint should return empty (not 500).
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0


# ───────────────────────────────────────────────────────────────────
# Honest status computation (added 2026-07-09 in P0 follow-up)
# ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_training_log_status_assigned_no_progress(client, db_session, make_tenant, make_user, make_course):
    """A row with an enrollment but no lesson progress AND no SCORM attempt
    must come back as computed_status='assigned' (not in_progress)."""
    tenant = await make_tenant(name="Acme", slug="acme-assigned")
    admin = await make_user(tenant, role="methodologist", email="admin@a.example")
    student = await make_user(tenant, role="student", email="stu@a.example")
    course = await make_course(tenant, admin, title="A1")
    await _enroll(db_session, student, course)

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["computed_status"] == "assigned"
    assert row["progress_percent"] == 0
    assert row["assignment_due_at"] is None
    assert row["deadline_state"] == "none"
    assert row["certificate_expires_at"] is None
    assert row["certificate_status"] == "none"


@pytest.mark.asyncio
async def test_training_log_due_policy_precedence_and_exact_enrollment_certificate(
    client, db_session, make_tenant, make_user, make_course, set_current_tenant
):
    from app.models.enrollment import Enrollment
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy
    from app.modules.certificates.models import Certificate
    from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
    from app.modules.training_log.repository import count_training_log, list_training_log
    from app.modules.training_log.schemas import TrainingLogFilter

    tenant = await make_tenant(name="Training log operational fields", slug="training-log-operational-fields")
    actor = await make_user(tenant, role="methodologist", email="operational-owner@example.test")
    learner = await make_user(tenant, role="student", email="operational-learner@example.test")
    course = await make_course(tenant, actor, title="Operational course")
    await set_current_tenant(tenant)

    now = datetime.now(UTC)
    legacy_enrollment = await _enroll(db_session, learner, course)
    rule = RecurringLearningRule(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        cadence_days=365,
        due_days=7,
        status="active",
        created_by=actor.id,
    )
    db_session.add(rule)
    await db_session.flush()
    occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id,
        rule_id=rule.id,
        user_id=learner.id,
        course_id=course.id,
        scheduled_for=now,
        due_at=now - timedelta(days=2),
        status="assigned",
    )
    db_session.add(occurrence)
    await db_session.flush()
    recurring_enrollment = Enrollment(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        recurring_assignment_id=occurrence.id,
        status="enrolled",
        source="recurring",
        enrolled_at=now,
    )
    db_session.add(recurring_enrollment)
    await db_session.flush()
    occurrence.enrollment_id = recurring_enrollment.id
    policy_due_at = now + timedelta(days=2)
    db_session.add(
        EnrollmentAccessPolicy(
            tenant_id=tenant.id,
            enrollment_id=recurring_enrollment.id,
            user_id=learner.id,
            due_at=policy_due_at,
        )
    )
    certificate_occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id,
        rule_id=rule.id,
        user_id=learner.id,
        course_id=course.id,
        scheduled_for=now - timedelta(days=30),
        due_at=now - timedelta(days=20),
        status="completed",
    )
    db_session.add(certificate_occurrence)
    await db_session.flush()
    certificate_enrollment = Enrollment(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        recurring_assignment_id=certificate_occurrence.id,
        status="completed",
        source="recurring",
        enrolled_at=now - timedelta(days=30),
        completed_at=now - timedelta(days=10),
    )
    db_session.add(certificate_enrollment)
    await db_session.flush()
    certificate_occurrence.enrollment_id = certificate_enrollment.id
    await db_session.flush()
    older_certificate_occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id,
        rule_id=rule.id,
        user_id=learner.id,
        course_id=course.id,
        scheduled_for=now - timedelta(days=60),
        due_at=now - timedelta(days=50),
        status="completed",
    )
    db_session.add(older_certificate_occurrence)
    await db_session.flush()
    older_certificate_enrollment = Enrollment(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        recurring_assignment_id=older_certificate_occurrence.id,
        status="completed",
        source="recurring",
        enrolled_at=now - timedelta(days=60),
        completed_at=now - timedelta(days=40),
    )
    db_session.add(older_certificate_enrollment)
    await db_session.flush()
    older_certificate_occurrence.enrollment_id = older_certificate_enrollment.id
    await db_session.flush()
    certificate = Certificate(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        enrollment_id=certificate_enrollment.id,
        certificate_number=f"TL-{uuid4().hex[:12]}",
        issued_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=now,
    )
    older_certificate = Certificate(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        enrollment_id=older_certificate_enrollment.id,
        certificate_number=f"TL-{uuid4().hex[:12]}",
        issued_at=now - timedelta(days=10),
        expires_at=now + timedelta(days=365),
    )
    db_session.add_all([older_certificate, certificate])
    await db_session.flush()

    rows = await list_training_log(db_session, tenant.id, TrainingLogFilter(), limit=10)
    by_enrollment = {row["enrollment_id"]: row for row in rows}
    legacy_row = by_enrollment[legacy_enrollment.id]
    recurring_row = by_enrollment[recurring_enrollment.id]
    certificate_row = by_enrollment[certificate_enrollment.id]
    older_certificate_row = by_enrollment[older_certificate_enrollment.id]

    assert legacy_row["assignment_due_at"] is None
    assert legacy_row["deadline_state"] == "none"
    assert legacy_row["certificate_id"] is None
    assert legacy_row["certificate_status"] == "none"
    assert recurring_row["assignment_due_at"] == policy_due_at
    assert recurring_row["deadline_state"] == "upcoming"
    assert recurring_row["deadline_status"] == "overdue"
    assert recurring_row["certificate_id"] is None
    assert recurring_row["certificate_status"] == "none"
    assert certificate_row["certificate_id"] == certificate.id
    assert certificate_row["certificate_expires_at"] == certificate.expires_at
    assert certificate_row["certificate_status"] == "revoked"
    assert older_certificate_row["certificate_id"] == older_certificate.id
    assert older_certificate_row["certificate_expires_at"] == older_certificate.expires_at
    assert older_certificate_row["certificate_status"] == "active"

    overdue_rows = await list_training_log(
        db_session,
        tenant.id,
        TrainingLogFilter(status="overdue"),
        limit=10,
    )
    assert recurring_enrollment.id in {row["enrollment_id"] for row in overdue_rows}
    assert await count_training_log(
        db_session,
        tenant.id,
        TrainingLogFilter(status="overdue"),
    ) == 1


@pytest.mark.asyncio
async def test_training_log_status_in_progress_native_lesson(
    client, db_session, make_tenant, make_user, make_course, make_module, make_lesson
):
    """Native course with one completed lesson progress row → in_progress,
    progress_percent = completed_lessons / total_lessons * 100."""
    tenant = await make_tenant(name="Acme", slug="acme-inprog")
    admin = await make_user(tenant, role="methodologist", email="admin@i.example")
    student = await make_user(tenant, role="student", email="stu@i.example")
    course = await make_course(tenant, admin, title="I1")
    module = await make_module(course, title="M1")
    l1 = await make_lesson(module, title="L1")
    await make_lesson(module, title="L2")
    await make_lesson(module, title="L3")
    await _enroll(db_session, student, course)

    # Mark lesson 1 as completed for this student.
    from app.models.progress import Progress

    p = Progress(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=student.id,
        course_id=course.id,
        lesson_id=l1.id,
        completed=True,
        completion_percent=100,
        percent=100,
    )
    db_session.add(p)
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?status=in_progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["computed_status"] == "in_progress"
    # 1 of 3 lessons → ~33%
    assert 30 <= row["progress_percent"] <= 34


@pytest.mark.asyncio
async def test_training_log_status_assigned_excludes_started(
    client, db_session, make_tenant, make_user, make_course, make_module, make_lesson
):
    """Filter status=assigned must NOT include rows that have any progress.
    Regression: before this fix the filter was a no-op (returned everything
    where completed_at IS NULL), which would surface 'in_progress' rows as
    'assigned' — misleading HR."""
    tenant = await make_tenant(name="Acme", slug="acme-aonly")
    admin = await make_user(tenant, role="methodologist", email="admin@ao.example")
    student = await make_user(tenant, role="student", email="stu@ao.example")
    course = await make_course(tenant, admin, title="AO1")
    module = await make_module(course, title="M1")
    lesson = await make_lesson(module, title="L")
    await _enroll(db_session, student, course)

    from app.models.progress import Progress

    p = Progress(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=student.id,
        course_id=course.id,
        lesson_id=lesson.id,
        completed=True,
        completion_percent=100,
        percent=100,
    )
    db_session.add(p)
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?status=assigned",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0  # student has progress → not 'assigned'


@pytest.mark.asyncio
async def test_training_log_status_in_progress_scorm_attempt(client, db_session, make_tenant, make_user, make_course):
    """SCORM course with a scorm_attempt row but no completed_at →
    computed_status='in_progress'."""
    tenant = await make_tenant(name="Acme", slug="acme-sip")
    admin = await make_user(tenant, role="methodologist", email="admin@sip.example")
    student = await make_user(tenant, role="student", email="stu@sip.example")
    course = await make_course(tenant, admin, title="Sip1", delivery_type="scorm")
    await _enroll(db_session, student, course)

    # Add a scorm_attempt to simulate a started SCORM attempt.
    from app.modules.scorm.models import ScormAttempt, ScormPackage

    pkg = ScormPackage(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        version="scorm_1_2",
        title="pkg",
        entrypoint="index.html",
        storage_key=f"scorm/{tenant.id}/{course.id}/x.zip",
        manifest_json={},
        uploaded_by=admin.id,
    )
    db_session.add(pkg)
    await db_session.flush()

    attempt = ScormAttempt(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        package_id=pkg.id,
        user_id=student.id,
        started_at=datetime.now(UTC),
        last_commit_at=datetime.now(UTC),
        cmi_json={},
    )
    db_session.add(attempt)
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?status=in_progress&delivery_type=scorm",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["computed_status"] == "in_progress"
    # SCORM progress map is a known simplification — 0 until completion.
    assert row["progress_percent"] == 0


@pytest.mark.asyncio
async def test_training_log_status_overdue_reads_immutable_cycle_deadline(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
):
    """Only cycle-linked unfinished enrollments can be honestly overdue."""
    from app.models.enrollment import Enrollment
    from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule

    tenant = await make_tenant(name="Acme", slug="acme-od")
    admin = await make_user(tenant, role="methodologist", email="admin@od.example")
    learner = await make_user(tenant, role="student", email="learner@od.example")
    course = await make_course(tenant, admin, title="Annual briefing")
    await set_current_tenant(tenant)

    now = datetime.now(UTC)
    rule = RecurringLearningRule(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        cadence_days=365,
        due_days=7,
        status="active",
        created_by=admin.id,
    )
    db_session.add(rule)
    await db_session.flush()
    occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id,
        rule_id=rule.id,
        user_id=learner.id,
        course_id=course.id,
        scheduled_for=now - timedelta(days=10),
        due_at=now - timedelta(days=3),
        status="assigned",
    )
    db_session.add(occurrence)
    await db_session.flush()
    enrollment = Enrollment(
        tenant_id=tenant.id,
        user_id=learner.id,
        course_id=course.id,
        recurring_assignment_id=occurrence.id,
        status="enrolled",
        source="recurring",
        enrolled_at=now - timedelta(days=10),
    )
    db_session.add(enrollment)
    await db_session.flush()
    occurrence.enrollment_id = enrollment.id
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?status=overdue",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["enrollment_id"] == str(enrollment.id)
    assert row["cycle_id"] == str(occurrence.id)
    assert row["cycle_type"] == "course"
    assert row["cycle_due_at"] is not None
    assert row["deadline_status"] == "overdue"
    assert datetime.fromisoformat(row["assignment_due_at"].replace("Z", "+00:00")) == occurrence.due_at
    assert row["deadline_state"] == "overdue"

    summary = await client.get(
        "/api/v1/admin/training-log/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["total"] == 1
    assert summary.json()["overdue"] == 1


@pytest.mark.asyncio
async def test_training_log_progress_percent_zero_lessons(client, db_session, make_tenant, make_user, make_course):
    """Native course with no lessons at all: progress_percent = 0 (not a
    divide-by-zero crash). Regression for the round() in repository."""
    tenant = await make_tenant(name="Acme", slug="acme-nol")
    admin = await make_user(tenant, role="methodologist", email="admin@nol.example")
    student = await make_user(tenant, role="student", email="stu@nol.example")
    course = await make_course(tenant, admin, title="NoLessons")
    await _enroll(db_session, student, course)

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    row = resp.json()["items"][0]
    assert row["progress_percent"] == 0
    assert row["computed_status"] == "assigned"


@pytest.mark.asyncio
async def test_training_log_path_cycle_deadlines_and_ineligible_cycles(
    client, db_session, make_tenant, make_user, make_course, set_current_tenant
):
    """Only active/completed recurring path cycles produce a frozen deadline."""
    from app.models.enrollment import Enrollment
    from app.modules.learning_cycles.models import (
        LearningPathCycleInstance,
        RecurringLearningAssignment,
        RecurringLearningRule,
    )
    from app.modules.learning_paths.models import LearningPath, LearningPathAssignment, LearningPathCourse
    from app.modules.training_log.repository import list_training_log
    from app.modules.training_log.schemas import TrainingLogFilter

    tenant = await make_tenant(name="Deadline eligibility", slug="deadline-eligibility")
    actor = await make_user(tenant, role="methodologist", email="deadline-owner@example.test")
    learner = await make_user(tenant, role="student", email="deadline-learner@example.test")
    course = await make_course(tenant, actor, title="Deadline course")
    await set_current_tenant(tenant)
    now = datetime.now(UTC)
    path = LearningPath(
        tenant_id=tenant.id, family_id=uuid4(), version=1, title="Recurring path", description="",
        status="draft", sequencing_mode="linear", created_by=actor.id,
    )
    db_session.add(path)
    await db_session.flush()
    db_session.add(LearningPathCourse(path_id=path.id, course_id=course.id, order_index=0))
    await db_session.flush()
    path.status = "published"
    await db_session.flush()
    rule = RecurringLearningRule(
        tenant_id=tenant.id, learning_path_id=path.id, user_id=learner.id, cadence_days=365,
        due_days=7, status="active", created_by=actor.id,
    )
    db_session.add(rule)
    await db_session.flush()

    sequence_no = 0

    async def path_enrollment(*, cycle_status: str, assignment_status: str, recurring: bool = True):
        nonlocal sequence_no
        sequence_no += 1
        cycle = LearningPathCycleInstance(
            tenant_id=tenant.id, rule_id=rule.id, path_id=path.id, user_id=learner.id,
            sequence_no=sequence_no, scheduled_for=now - timedelta(days=10),
            due_at=now - timedelta(days=1), status=cycle_status,
            completed_at=now if cycle_status == "completed" else None,
        )
        db_session.add(cycle)
        await db_session.flush()
        assignment = LearningPathAssignment(
            tenant_id=tenant.id, path_id=path.id, user_id=learner.id, assigned_by=actor.id,
            source="recurring" if recurring else "manual", recurrence_instance_id=cycle.id if recurring else None,
            due_at=now + timedelta(days=5), status=assignment_status,
        )
        db_session.add(assignment)
        await db_session.flush()
        enrollment = Enrollment(
            tenant_id=tenant.id, user_id=learner.id, course_id=course.id,
            learning_path_assignment_id=assignment.id, status="enrolled", source="learning_path",
            enrolled_at=now - timedelta(days=10),
        )
        db_session.add(enrollment)
        await db_session.flush()
        return enrollment, cycle

    active_enrollment, active_cycle = await path_enrollment(cycle_status="active", assignment_status="active")
    cancelled_cycle, _ = await path_enrollment(cycle_status="cancelled", assignment_status="active")
    skipped_path_cycle, _ = await path_enrollment(cycle_status="skipped", assignment_status="active")
    cancelled_assignment, _ = await path_enrollment(cycle_status="active", assignment_status="cancelled")
    manual_path, _ = await path_enrollment(cycle_status="active", assignment_status="active", recurring=False)
    direct_rule = RecurringLearningRule(
        tenant_id=tenant.id, course_id=course.id, user_id=learner.id, cadence_days=365,
        due_days=7, status="active", created_by=actor.id,
    )
    db_session.add(direct_rule)
    await db_session.flush()
    skipped_occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id, rule_id=direct_rule.id, user_id=learner.id, course_id=course.id,
        scheduled_for=now - timedelta(days=10), due_at=now - timedelta(days=1), status="skipped",
    )
    db_session.add(skipped_occurrence)
    await db_session.flush()
    skipped_enrollment = Enrollment(
        tenant_id=tenant.id, user_id=learner.id, course_id=course.id,
        recurring_assignment_id=skipped_occurrence.id, status="enrolled", source="recurring",
        enrolled_at=now - timedelta(days=10),
    )
    db_session.add(skipped_enrollment)
    await db_session.flush()

    rows = await list_training_log(db_session, tenant.id, TrainingLogFilter(), limit=20)
    by_id = {row["enrollment_id"]: row for row in rows}
    assert by_id[active_enrollment.id]["cycle_id"] == active_cycle.id
    assert by_id[active_enrollment.id]["cycle_due_at"] == active_cycle.due_at
    assert by_id[active_enrollment.id]["deadline_status"] == "overdue"
    assert by_id[active_enrollment.id]["assignment_due_at"] == active_cycle.due_at
    assert by_id[active_enrollment.id]["deadline_state"] == "overdue"
    for enrollment in (cancelled_cycle, skipped_path_cycle, cancelled_assignment, manual_path, skipped_enrollment):
        assert by_id[enrollment.id]["deadline_status"] == "not_applicable"
    overdue_rows = await list_training_log(db_session, tenant.id, TrainingLogFilter(status="overdue"), limit=20)
    assert [row["enrollment_id"] for row in overdue_rows] == [active_enrollment.id]


@pytest.mark.asyncio
async def test_training_log_completed_status_without_timestamp_is_completed_not_overdue(
    client, db_session, make_tenant, make_user, make_course
):
    from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
    from app.modules.training_log.repository import list_training_log
    from app.modules.training_log.schemas import TrainingLogFilter

    tenant = await make_tenant(name="Completed state", slug="completed-state")
    admin = await make_user(tenant, role="methodologist", email="completed-admin@example.com")
    learner = await make_user(tenant, role="student", email="completed-learner@example.test")
    course = await make_course(tenant, admin, title="Completed course")
    now = datetime.now(UTC)
    rule = RecurringLearningRule(
        tenant_id=tenant.id, course_id=course.id, user_id=learner.id,
        cadence_days=365, due_days=7, status="active", created_by=admin.id,
    )
    db_session.add(rule)
    await db_session.flush()
    occurrence = RecurringLearningAssignment(
        tenant_id=tenant.id, rule_id=rule.id, user_id=learner.id, course_id=course.id,
        scheduled_for=now - timedelta(days=10), due_at=now - timedelta(days=1), status="assigned",
    )
    db_session.add(occurrence)
    await db_session.flush()
    enrollment = await _enroll(
        db_session,
        learner,
        course,
        status="completed",
        source="recurring",
        recurring_assignment_id=occurrence.id,
        completed_at=None,
    )
    occurrence.enrollment_id = enrollment.id
    await db_session.flush()

    rows = await list_training_log(db_session, tenant.id, TrainingLogFilter(), limit=10)
    assert rows[0]["computed_status"] == "completed"
    assert rows[0]["deadline_status"] == "not_applicable"
    assert rows[0]["assignment_due_at"] == occurrence.due_at
    assert rows[0]["deadline_state"] == "none"
    assert await list_training_log(db_session, tenant.id, TrainingLogFilter(status="overdue"), limit=10) == []
    token = await _login(client, admin)
    summary = await client.get("/api/v1/admin/training-log/summary", headers={"Authorization": f"Bearer {token}"})
    assert summary.status_code == 200, summary.text
    assert summary.json() == {
        "total": 1,
        "assigned": 0,
        "in_progress": 0,
        "completed": 1,
        "overdue": 0,
        "failed_current": 0,
        "exhausted_attempts": 0,
        "reassigned": 0,
        "cancelled_history": 0,
        "superseded_history": 0,
    }


@pytest.mark.asyncio
async def test_training_log_equal_due_and_completion_is_on_time_and_pagination_uses_enrollment_id(
    client, db_session, make_tenant, make_user, make_course, set_current_tenant
):
    from app.models.enrollment import Enrollment
    from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
    from app.modules.training_log.repository import list_training_log
    from app.modules.training_log.schemas import TrainingLogFilter

    tenant = await make_tenant(name="Stable deadline page", slug="stable-deadline-page")
    actor = await make_user(tenant, role="methodologist", email="stable-owner@example.test")
    learner = await make_user(tenant, role="student", email="stable-learner@example.test")
    course = await make_course(tenant, actor, title="Stable course")
    await set_current_tenant(tenant)
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    rule = RecurringLearningRule(tenant_id=tenant.id, course_id=course.id, user_id=learner.id, cadence_days=365, due_days=7, status="active", created_by=actor.id)
    db_session.add(rule)
    await db_session.flush()
    occurrence = RecurringLearningAssignment(tenant_id=tenant.id, rule_id=rule.id, user_id=learner.id, course_id=course.id, scheduled_for=stamp, due_at=stamp, status="completed")
    db_session.add(occurrence)
    await db_session.flush()
    first = Enrollment(id=uuid4(), tenant_id=tenant.id, user_id=learner.id, course_id=course.id, recurring_assignment_id=occurrence.id, status="completed", completed_at=stamp, enrolled_at=stamp, source="recurring")
    second = Enrollment(id=uuid4(), tenant_id=tenant.id, user_id=learner.id, course_id=course.id, status="enrolled", enrolled_at=stamp, source="manual")
    db_session.add_all([first, second])
    await db_session.flush()
    occurrence.enrollment_id = first.id
    await db_session.flush()

    full = await list_training_log(db_session, tenant.id, TrainingLogFilter(), limit=10)
    first_page = await list_training_log(db_session, tenant.id, TrainingLogFilter(), limit=1, offset=0)
    second_page = await list_training_log(db_session, tenant.id, TrainingLogFilter(), limit=1, offset=1)
    assert next(row for row in full if row["enrollment_id"] == first.id)["deadline_status"] == "completed_on_time"
    assert next(row for row in full if row["enrollment_id"] == first.id)["deadline_state"] == "completed_on_time"
    assert [row["enrollment_id"] for row in first_page + second_page] == [row["enrollment_id"] for row in full]
    assert [row["enrollment_id"] for row in full] == sorted([first.id, second.id])


@pytest.mark.asyncio
async def test_training_log_repository_lms_app_rls_hides_other_tenant_rows_and_counts(
    client, db_session, make_tenant, make_user, make_course, set_current_tenant
):
    from sqlalchemy import text

    from app.modules.training_log.repository import count_training_log, list_training_log
    from app.modules.training_log.schemas import TrainingLogFilter

    can_assume = await db_session.scalar(text(
        "SELECT rolsuper OR current_user = 'lms_app' "
        "FROM pg_roles WHERE rolname = current_user"
    ))
    if not can_assume:
        pytest.skip("Runtime RLS gate unavailable: current DEV role cannot assume lms_app; do not grant privileges in tests")

    tenant_a = await make_tenant(name="Training log RLS A", slug="training-log-rls-a")
    tenant_b = await make_tenant(name="Training log RLS B", slug="training-log-rls-b")
    admin_a = await make_user(tenant_a, role="methodologist", email="rls-admin-a@example.test")
    learner_a = await make_user(tenant_a, role="student", email="rls-learner-a@example.test")
    learner_b = await make_user(tenant_b, role="student", email="rls-learner-b@example.test")
    course_a = await make_course(tenant_a, admin_a, title="RLS A course")
    course_b = await make_course(tenant_b, learner_b, title="RLS B course")
    await set_current_tenant(tenant_a)
    await _enroll(db_session, learner_a, course_a)
    await set_current_tenant(tenant_b)
    await _enroll(db_session, learner_b, course_b)

    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    try:
        role = (await db_session.execute(text(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ))).one()
        assert tuple(role) == ("lms_app", False, False)
        await set_current_tenant(tenant_a)
        rows_a = await list_training_log(db_session, tenant_a.id, TrainingLogFilter(), limit=10)
        count_a = await count_training_log(db_session, tenant_a.id, TrainingLogFilter())
        assert await count_training_log(db_session, tenant_b.id, TrainingLogFilter()) == 0
        assert await list_training_log(db_session, tenant_b.id, TrainingLogFilter(), limit=10) == []
        assert await db_session.scalar(text("SELECT count(*) FROM enrollments WHERE tenant_id = :tid"), {"tid": tenant_b.id}) == 0
        await set_current_tenant(tenant_b)
        rows_b = await list_training_log(db_session, tenant_b.id, TrainingLogFilter(), limit=10)
        count_b = await count_training_log(db_session, tenant_b.id, TrainingLogFilter())
        assert [row["user_id"] for row in rows_a] == [learner_a.id]
        assert count_a == 1
        assert [row["user_id"] for row in rows_b] == [learner_b.id]
        assert count_b == 1
    finally:
        await db_session.execute(text("RESET ROLE"))
