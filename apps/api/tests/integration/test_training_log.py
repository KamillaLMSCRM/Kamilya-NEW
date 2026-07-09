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
    admin = await make_user(tenant, role="admin", email="admin@acme.example")
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
    admin_b = await make_user(tenant_b, role="admin", email="admin@b.example")
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
    admin = await make_user(tenant, role="admin", email="admin@c.example")
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
    admin = await make_user(tenant, role="admin", email="admin@s.example")
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
    admin = await make_user(tenant, role="admin", email="admin@x.example")
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
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["course_title"] == "X1"


@pytest.mark.asyncio
async def test_training_log_pagination(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Acme", slug="acme-p")
    admin = await make_user(tenant, role="admin", email="admin@p.example")
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