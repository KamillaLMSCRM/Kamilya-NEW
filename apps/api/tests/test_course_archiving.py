from __future__ import annotations

import pytest

from app.modules.courses.release_models import ContentRelease


pytestmark = pytest.mark.asyncio


async def test_archiving_preserves_release_and_hides_course_from_default_list(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    auth_headers,
):
    tenant = await make_tenant(name="Archive tenant")
    methodologist = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, methodologist, title="Published course")
    release = ContentRelease(
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot={"course_id": str(course.id)},
        snapshot_sha256="0" * 64,
        published_by=methodologist.id,
    )
    db_session.add(release)
    await db_session.flush()
    course.status = "published"
    course.current_release_id = release.id
    await db_session.flush()

    archived = await client.post(
        f"/api/v1/courses/{course.id}/archive",
        headers=auth_headers(methodologist),
    )

    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert archived.json()["current_release_id"] == str(release.id)

    active = await client.get("/api/v1/courses", headers=auth_headers(methodologist))
    assert active.status_code == 200, active.text
    assert str(course.id) not in {item["id"] for item in active.json()}

    archive = await client.get(
        "/api/v1/courses?status=archived",
        headers=auth_headers(methodologist),
    )
    assert archive.status_code == 200, archive.text
    assert str(course.id) in {item["id"] for item in archive.json()}


async def test_archive_course_returns_404_for_other_tenant(
    client,
    make_tenant,
    make_user,
    make_course,
    auth_headers,
):
    tenant_a = await make_tenant(name="Tenant A")
    user_a = await make_user(tenant_a, role="methodologist")
    course = await make_course(tenant_a, user_a)

    tenant_b = await make_tenant(name="Tenant B")
    user_b = await make_user(tenant_b, role="methodologist")

    response = await client.post(
        f"/api/v1/courses/{course.id}/archive",
        headers=auth_headers(user_b),
    )

    assert response.status_code == 404
