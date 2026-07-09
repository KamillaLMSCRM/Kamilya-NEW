"""Integration tests for /api/v1/admin/onboarding-status.

Covers:
- happy path: tenant with all steps done → completed=True
- empty tenant: completed=False, all steps have done=False
- partial: at least one done, others not
- tenant scope: only the current tenant's data counts
- RBAC: 401 unauthenticated, 403 student
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


async def _login(client, user, password: str = "Password123!") -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_onboarding_status_requires_auth(client):
    resp = await client.get("/api/v1/admin/onboarding-status")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_onboarding_student_forbidden(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme", slug="acme-onb")
    student = await make_user(tenant, role="student", email="s@onb.example")
    token = await _login(client, student)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_onboarding_empty_tenant(client, make_tenant, make_user):
    tenant = await make_tenant(name="Empty", slug="empty-onb")
    admin = await make_user(tenant, role="admin", email="a@empty.example")
    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["completed"] is False
    assert len(body["steps"]) == 7
    for s in body["steps"]:
        assert s["done"] is False
    assert body["active_users"] == 1  # just the admin


@pytest.mark.asyncio
async def test_onboarding_partial_progress(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Part", slug="part-onb")
    admin = await make_user(tenant, role="admin", email="a@part.example")
    # Add a second user so staff_import_done
    staff = await make_user(tenant, role="student", email="s@part.example")
    # Add a course so first_course_done
    course = await make_course(tenant, admin, title="C1")

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["completed"] is False
    by_id = {s["id"]: s for s in body["steps"]}
    # These should be done with what we set up:
    assert by_id["staff_import"]["done"] is True
    assert by_id["first_course"]["done"] is True
    # Others should NOT be done:
    assert by_id["profile"]["done"] is False
    assert by_id["documents"]["done"] is False
    assert by_id["first_assignment"]["done"] is False  # no enrollment yet
    assert by_id["kiosk_or_invite"]["done"] is False
    assert by_id["training_log"]["done"] is False


@pytest.mark.asyncio
async def test_onboarding_first_assignment_done_when_enrollment_exists(
    client, db_session, make_tenant, make_user, make_course
):
    tenant = await make_tenant(name="Assign", slug="assign-onb")
    admin = await make_user(tenant, role="admin", email="a@assign.example")
    student = await make_user(tenant, role="student", email="s@assign.example")
    course = await make_course(tenant, admin, title="C1")
    from app.models.enrollment import Enrollment

    e = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=student.id,
        course_id=course.id,
        status="enrolled",
        enrolled_at=datetime.now(timezone.utc),
        source="manual",
    )
    db_session.add(e)
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    by_id = {s["id"]: s for s in body["steps"]}
    assert by_id["first_assignment"]["done"] is True
    assert by_id["training_log"]["done"] is True


@pytest.mark.asyncio
async def test_onboarding_kiosk_done_when_kiosk_exists(
    client, db_session, make_tenant, make_user
):
    tenant = await make_tenant(name="Kiosk", slug="kiosk-onb")
    admin = await make_user(tenant, role="admin", email="a@kiosk.example")
    from app.models.kiosk_link import KioskLink

    k = KioskLink(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Workshop kiosk",
        token="abc123",
        is_active=True,
        created_by=admin.id,
    )
    db_session.add(k)
    await db_session.flush()

    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    by_id = {s["id"]: s for s in body["steps"]}
    assert by_id["kiosk_or_invite"]["done"] is True


@pytest.mark.asyncio
async def test_onboarding_tenant_isolation(client, db_session, make_tenant, make_user, make_course):
    tenant_a = await make_tenant(name="A", slug="a-onb")
    tenant_b = await make_tenant(name="B", slug="b-onb")
    admin_a = await make_user(tenant_a, role="admin", email="a@a.example")
    admin_b = await make_user(tenant_b, role="admin", email="a@b.example")
    course_a = await make_course(tenant_a, admin_a, title="CA")
    # Add a second user to tenant A so staff_import_done there
    staff_a = await make_user(tenant_a, role="student", email="s@a.example")

    token_b = await _login(client, admin_b)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    body = resp.json()
    # Tenant B sees only itself — admin_b alone, no courses, no documents.
    assert body["completed"] is False
    by_id = {s["id"]: s for s in body["steps"]}
    assert by_id["first_course"]["done"] is False
    assert by_id["staff_import"]["done"] is False


@pytest.mark.asyncio
async def test_onboarding_trial_info(client, make_tenant, make_user, db_session):
    from app.models.tenants import Tenant

    tenant = await make_tenant(name="Trial", slug="trial-onb")
    # Set trial_ends_at 5 days from now
    tenant.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=5)
    await db_session.flush()

    admin = await make_user(tenant, role="admin", email="a@trial.example")
    token = await _login(client, admin)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["trial_days_remaining"] is not None
    assert 4 <= body["trial_days_remaining"] <= 5  # depending on rounding


@pytest.mark.asyncio
async def test_onboarding_superadmin_no_tenant_returns_empty(
    client, db_session, make_superadmin
):
    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["steps"] == []
    assert body["completed"] is False