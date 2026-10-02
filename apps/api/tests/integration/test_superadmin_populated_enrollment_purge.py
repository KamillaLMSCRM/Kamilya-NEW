"""Regression coverage for deleting a tenant with populated enrollments."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.models.assignment_access import AssignmentAccessCredential
from app.models.course_assignment_notification import CourseAssignmentNotificationOutbox
from app.models.enrollment import Enrollment
from app.models.enrollment_access_policy import EnrollmentAccessPolicy
from app.models.users import User
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.methodologist_workbench.assignment_models import AssignmentPlan


async def _login(client, user: User, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _set_runtime_role(db_session) -> None:
    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    role = (
        await db_session.execute(
            text(
                "SELECT current_user, rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user"
            )
        )
    ).one()
    assert role == ("lms_app", False, False)


@pytest.mark.asyncio
async def test_superadmin_delete_populated_enrollment_tenant_cleans_restrict_children(
    client,
    db_session,
    make_tenant,
    make_user,
    make_superadmin,
    set_current_tenant,
):
    """A populated tenant purge removes enrollment dependants and preserves another tenant."""
    target = await make_tenant(
        name="Populated enrollment purge",
        slug=f"populated-enrollment-{uuid4().hex[:8]}",
    )
    sentinel = await make_tenant(
        name="Purge sentinel",
        slug=f"purge-sentinel-{uuid4().hex[:8]}",
    )

    await set_current_tenant(target)
    methodologist = await make_user(target, role="methodologist")
    learner_a = await make_user(target, role="student")
    learner_b = await make_user(target, role="student")
    course = Course(
        tenant_id=target.id,
        title="Published enrollment purge course",
        description="Synthetic populated purge fixture",
        status="published",
        review_status="approved",
    )
    db_session.add(course)
    await db_session.flush()
    release = ContentRelease(
        tenant_id=target.id,
        course_id=course.id,
        version=1,
        snapshot={"course": "synthetic"},
        snapshot_sha256="1" * 64,
    )
    db_session.add(release)
    await db_session.flush()
    course.current_release_id = release.id

    enrollment_a = Enrollment(
        tenant_id=target.id,
        course_id=course.id,
        user_id=learner_a.id,
        content_release_id=release.id,
        status="enrolled",
    )
    enrollment_b = Enrollment(
        tenant_id=target.id,
        course_id=course.id,
        user_id=learner_b.id,
        content_release_id=release.id,
        status="in_progress",
    )
    db_session.add_all([enrollment_a, enrollment_b])
    await db_session.flush()

    expiry = datetime.now(UTC) + timedelta(hours=1)
    db_session.add_all(
        [
            AssignmentAccessCredential(
                tenant_id=target.id,
                enrollment_id=enrollment_a.id,
                user_id=learner_a.id,
                token_hash=f"token-{uuid4().hex}",
                pin_hash="pin-hash",
                expires_at=expiry,
            ),
            EnrollmentAccessPolicy(
                tenant_id=target.id,
                enrollment_id=enrollment_a.id,
                user_id=learner_a.id,
                delivery_mode="personal_link",
                link_expires_at=expiry,
            ),
            CourseAssignmentNotificationOutbox(
                tenant_id=target.id,
                enrollment_id=enrollment_b.id,
                assigned_by=methodologist.id,
                status="pending",
            ),
        ]
    )

    # The workbench plan contract requires a ready row before the successful receipt.
    plan_id = uuid4()
    plan = AssignmentPlan(
        id=plan_id,
        tenant_id=target.id,
        actor_id=methodologist.id,
        snapshot={"tenant_id": str(target.id), "actor_id": str(methodologist.id), "plan_id": str(plan_id)},
        preview={"plan_id": str(plan_id), "fingerprint": "2" * 64},
        fingerprint="2" * 64,
        expires_at=expiry,
        status="ready",
    )
    db_session.add(plan)
    await db_session.flush()
    plan.status = "succeeded"
    plan.receipt = {"fixture": "complete"}
    await db_session.flush()

    await set_current_tenant(sentinel)
    sentinel_user = await make_user(sentinel, role="student")
    sentinel_course = Course(
        tenant_id=sentinel.id,
        title="Sentinel course",
        description="Must survive another tenant purge",
        status="published",
        review_status="approved",
    )
    db_session.add(sentinel_course)
    await db_session.flush()
    target_id, target_slug = target.id, target.slug
    sentinel_id = sentinel.id
    sentinel_user_id, sentinel_course_id = sentinel_user.id, sentinel_course.id
    await db_session.commit()

    superadmin = await make_superadmin()
    token = await _login(client, superadmin, "SuperPass123!")
    headers = {"Authorization": f"Bearer {token}"}
    await _set_runtime_role(db_session)

    response = await client.delete(
        f"/api/v1/admin/super/tenants/{target_id}?confirm_slug={target_slug}",
        headers=headers,
    )
    assert response.status_code == 204, response.text

    # Production GET opens a new session; this transactional test client shares
    # one. Raw SQL DELETE must not leave its pre-delete Tenant in the identity map.
    db_session.expire_all()
    readback = await client.get(
        f"/api/v1/admin/super/tenants/{target_id}",
        headers=headers,
    )
    assert readback.status_code == 404, readback.text

    await set_current_tenant(target_id)
    await _set_runtime_role(db_session)
    assert await db_session.scalar(select(Enrollment.id).where(Enrollment.tenant_id == target_id)) is None
    assert (
        await db_session.scalar(
            select(AssignmentAccessCredential.id).where(
                AssignmentAccessCredential.tenant_id == target_id
            )
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(EnrollmentAccessPolicy.id).where(EnrollmentAccessPolicy.tenant_id == target_id)
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(CourseAssignmentNotificationOutbox.id).where(
                CourseAssignmentNotificationOutbox.tenant_id == target_id
            )
        )
        is None
    )
    assert await db_session.scalar(select(AssignmentPlan.id).where(AssignmentPlan.tenant_id == target_id)) is None

    sentinel_readback = await client.get(
        f"/api/v1/admin/super/tenants/{sentinel_id}",
        headers=headers,
    )
    assert sentinel_readback.status_code == 200, sentinel_readback.text
    assert sentinel_readback.json()["id"] == str(sentinel_id)
    await set_current_tenant(sentinel_id)
    await _set_runtime_role(db_session)
    assert await db_session.scalar(select(User.id).where(User.id == sentinel_user_id)) == sentinel_user_id
    assert (
        await db_session.scalar(select(Course.id).where(Course.id == sentinel_course_id))
        == sentinel_course_id
    )
