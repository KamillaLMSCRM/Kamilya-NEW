"""Integration tests for /api/v1/admin/onboarding-status.

Covers:
- happy path: tenant with all steps done → completed=True
- empty tenant: completed=False, all steps have done=False
- partial: at least one done, others not
- tenant scope: only the current tenant's data counts
- RBAC: 401 unauthenticated, 403 student
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    assert [step["id"] for step in body["steps"]] == ["team"]
    for s in body["steps"]:
        assert s["done"] is False
    assert body["active_users"] == 1  # just the admin


@pytest.mark.asyncio
async def test_onboarding_partial_progress(client, db_session, make_tenant, make_user, make_course):
    tenant = await make_tenant(name="Part", slug="part-onb")
    admin = await make_user(tenant, role="admin", email="a@part.example")
    methodologist = await make_user(tenant, role="methodologist", email="m@part.example")
    # Add a second user so staff_import_done
    await make_user(tenant, role="student", email="s@part.example")
    # Add a course so first_course_done
    await make_course(tenant, admin, title="C1")

    token = await _login(client, methodologist)
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
    assert by_id["documents"]["done"] is False
    assert by_id["first_assignment"]["done"] is False  # no enrollment yet
    assert by_id["training_log"]["done"] is False


@pytest.mark.asyncio
async def test_onboarding_first_assignment_done_when_enrollment_exists(
    client, db_session, make_tenant, make_user, make_course
):
    tenant = await make_tenant(name="Assign", slug="assign-onb")
    admin = await make_user(tenant, role="admin", email="a@assign.example")
    methodologist = await make_user(tenant, role="methodologist", email="m@assign.example")
    student = await make_user(tenant, role="student", email="s@assign.example")
    course = await make_course(tenant, admin, title="C1")
    from app.models.enrollment import Enrollment

    e = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        user_id=student.id,
        course_id=course.id,
        status="enrolled",
        enrolled_at=datetime.now(UTC),
        source="manual",
    )
    db_session.add(e)
    await db_session.flush()

    token = await _login(client, methodologist)
    resp = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    by_id = {s["id"]: s for s in body["steps"]}
    assert by_id["first_assignment"]["done"] is True
    assert by_id["training_log"]["done"] is False

    e.status = "completed"
    e.completed_at = datetime.now(UTC)
    await db_session.flush()
    response = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    by_id = {s["id"]: s for s in response.json()["steps"]}
    assert by_id["training_log"]["done"] is True


@pytest.mark.asyncio
async def test_onboarding_tenant_isolation(client, db_session, make_tenant, make_user, make_course):
    tenant_a = await make_tenant(name="A", slug="a-onb")
    tenant_b = await make_tenant(name="B", slug="b-onb")
    admin_a = await make_user(tenant_a, role="admin", email="a@a.example")
    await make_user(tenant_b, role="admin", email="a@b.example")
    methodologist_b = await make_user(tenant_b, role="methodologist", email="m@b.example")
    await make_course(tenant_a, admin_a, title="CA")
    # Add a second user to tenant A so staff_import_done there
    await make_user(tenant_a, role="student", email="s@a.example")

    token_b = await _login(client, methodologist_b)
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
    tenant = await make_tenant(name="Trial", slug="trial-onb")
    # Set trial_ends_at 5 days from now
    tenant.trial_ends_at = datetime.now(UTC) + timedelta(days=5)
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
@pytest.mark.parametrize(
    ("days", "expected_state"),
    [(10, "active"), (2, "nearing_expiry")],
)
async def test_onboarding_exposes_trial_lifecycle_state(
    client, make_tenant, make_user, db_session, days, expected_state
):
    tenant = await make_tenant(
        name="Lifecycle trial",
        slug=f"lifecycle-{days}-onb",
        status="trial",
        plan="trial",
        settings={"trial_limits": {"ai_course_generations_limit": 1}},
    )
    tenant.trial_ends_at = datetime.now(UTC) + timedelta(days=days)
    await db_session.flush()
    admin = await make_user(tenant, role="admin", email=f"admin-{days}@lifecycle.example")

    response = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {await _login(client, admin)}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trial_state"] == expected_state
    assert body["trial_access_state"] == ("limited" if expected_state == "nearing_expiry" else "available")


@pytest.mark.asyncio
async def test_onboarding_exposes_exact_role_owned_steps_and_canonical_links(
    client, make_tenant, make_user
):
    tenant = await make_tenant(name="Role onboarding", slug="role-owned-onb")
    admin = await make_user(tenant, role="admin", email="admin@role-owned.example")
    methodologist = await make_user(
        tenant, role="methodologist", email="methodologist@role-owned.example"
    )

    admin_body = (await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {await _login(client, admin)}"},
    )).json()
    methodologist_body = (await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {await _login(client, methodologist)}"},
    )).json()

    assert admin_body["role"] == "admin"
    assert methodologist_body["role"] == "methodologist"
    admin_steps = {step["id"]: step for step in admin_body["steps"]}
    assert set(admin_steps) == {"team"}
    assert admin_steps["team"]["owner"] == "admin"
    assert admin_steps["team"]["href"] == "/admin/team"
    assert admin_steps["team"]["done"] is True

    methodologist_steps = {
        step["id"]: step for step in methodologist_body["steps"]
    }
    assert set(methodologist_steps) == {
        "staff_import",
        "documents",
        "first_course",
        "first_assignment",
        "training_log",
    }
    assert methodologist_steps["first_course"]["owner"] == "methodologist"
    assert methodologist_steps["first_assignment"]["owner"] == "methodologist"
    assert methodologist_steps["first_assignment"]["href"] == "/courses"
    assert methodologist_steps["training_log"]["href"] == "/training-log"
    assert all(
        step["href"] not in {"/assignments", "/invitations"}
        for step in methodologist_steps.values()
    )


@pytest.mark.asyncio
async def test_onboarding_exhausted_active_trial_is_limited_not_support_required(
    client, make_tenant, make_user, db_session, set_current_tenant
):
    from app.models.tenants import TenantUsage

    tenant = await make_tenant(
        name="Limited trial",
        slug="limited-trial-onb",
        status="trial",
        plan="trial",
        settings={"trial_limits": {"ai_course_generations_limit": 1}},
    )
    tenant.trial_ends_at = datetime.now(UTC) + timedelta(days=10)
    await set_current_tenant(tenant)
    db_session.add(TenantUsage(tenant_id=tenant.id, ai_course_generations_used=1))
    await db_session.flush()
    admin = await make_user(tenant, role="admin", email="admin@limited.example")

    response = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {await _login(client, admin)}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trial_state"] == "active"
    assert body["trial_access_state"] == "limited"
    assert body["trial_exhausted_limits"] == ["ai_courses"]


@pytest.mark.asyncio
async def test_onboarding_marks_expired_and_exhausted_trial_as_support_required(
    client, make_tenant, make_user, db_session, set_current_tenant
):
    from app.models.tenants import TenantUsage

    tenant = await make_tenant(
        name="Exhausted trial",
        slug="exhausted-trial-onb",
        status="trial",
        plan="trial",
        settings={
            "trial_limits": {
                "ai_course_generations_limit": 1,
                "jd_course_generations_limit": 1,
                "max_students": 1,
                "system_users_limit": 2,
            }
        },
    )
    tenant.trial_ends_at = datetime.now(UTC) - timedelta(minutes=1)
    await set_current_tenant(tenant)
    db_session.add(
        TenantUsage(
            tenant_id=tenant.id,
            ai_course_generations_used=1,
            jd_course_generations_used=1,
        )
    )
    await db_session.flush()
    admin = await make_user(tenant, role="admin", email="admin@exhausted.example")
    token = await _login(client, admin)

    response = await client.get(
        "/api/v1/admin/onboarding-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trial_state"] == "expired"
    assert body["trial_access_state"] == "support_required"
    assert set(body["trial_exhausted_limits"]) >= {"ai_courses", "jd_courses"}
    assert body["trial_usage"]["ai_courses"] == {
        "used": 1,
        "limit": 1,
        "remaining": 0,
    }


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
