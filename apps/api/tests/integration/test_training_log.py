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


async def _enroll(db, user, course):
    """Insert an enrollment row directly (faster than HTTP-driven flow)."""
    from datetime import datetime, timezone

    from app.models.enrollment import Enrollment

    e = Enrollment(
        id=uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        course_id=course.id,
        status="enrolled",
        enrolled_at=datetime.now(timezone.utc),
        source="manual",
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
    from datetime import datetime, timezone

    enrollment.status = "completed"
    enrollment.completed_at = datetime.now(timezone.utc)
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
    assert before.json() == {"total": 0, "assigned": 0, "in_progress": 0, "completed": 0}

    enrollment = await _enroll(db_session, student, course)
    after_assignment = await client.get(
        "/api/v1/admin/training-log/summary?course_id=" + str(course.id), headers=headers
    )
    table_after_assignment = await client.get(
        "/api/v1/admin/training-log?course_id=" + str(course.id), headers=headers
    )
    assert after_assignment.json() == {"total": 1, "assigned": 1, "in_progress": 0, "completed": 0}
    assert table_after_assignment.json()["total"] == after_assignment.json()["total"]

    from datetime import datetime, timezone

    enrollment.status = "completed"
    enrollment.completed_at = datetime.now(timezone.utc)
    await db_session.flush()
    after_completion = await client.get(
        "/api/v1/admin/training-log/summary?course_id=" + str(course.id), headers=headers
    )
    table_after_completion = await client.get(
        "/api/v1/admin/training-log?course_id=" + str(course.id), headers=headers
    )
    assert after_completion.json() == {"total": 1, "assigned": 0, "in_progress": 0, "completed": 1}
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
async def test_training_log_status_assigned_no_progress(
    client, db_session, make_tenant, make_user, make_course
):
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
async def test_training_log_status_in_progress_scorm_attempt(
    client, db_session, make_tenant, make_user, make_course
):
    """SCORM course with a scorm_attempt row but no completed_at →
    computed_status='in_progress'."""
    tenant = await make_tenant(name="Acme", slug="acme-sip")
    admin = await make_user(tenant, role="methodologist", email="admin@sip.example")
    student = await make_user(tenant, role="student", email="stu@sip.example")
    course = await make_course(
        tenant, admin, title="Sip1", delivery_type="scorm"
    )
    await _enroll(db_session, student, course)

    # Add a scorm_attempt to simulate a started SCORM attempt.
    from datetime import datetime, timezone

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
        started_at=datetime.now(timezone.utc),
        last_commit_at=datetime.now(timezone.utc),
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
async def test_training_log_status_overdue_returns_422(
    client, db_session, make_tenant, make_user
):
    """status=overdue was removed (no deadline column on enrollments). The
    Pydantic Literal must reject it with 422, not silently ignore."""
    tenant = await make_tenant(name="Acme", slug="acme-od")
    admin = await make_user(tenant, role="methodologist", email="admin@od.example")

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/training-log?status=overdue",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    # Error message must mention the offending field so HR can debug.
    body = resp.json()
    detail_blob = str(body)
    assert "overdue" in detail_blob.lower() or "status" in detail_blob.lower()


@pytest.mark.asyncio
async def test_training_log_progress_percent_zero_lessons(
    client, db_session, make_tenant, make_user, make_course
):
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
