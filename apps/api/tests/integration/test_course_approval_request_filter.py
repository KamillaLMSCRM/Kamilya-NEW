"""Selected course audit requests must not mix courses or tenants."""
import pytest


@pytest.mark.asyncio
async def test_course_request_filter_preserves_legacy_and_tenant_scope(
    client, db_session, make_tenant, make_user, make_course, auth_headers, set_current_tenant,
):
    from app.modules.course_approval.models import CourseApprovalRequest, CourseApprovalRevision
    from app.modules.courses.release_service import canonical_json_sha256

    tenant_a = await make_tenant(name="Request filter QA A")
    tenant_b = await make_tenant(name="Request filter QA B")
    author_a = await make_user(tenant_a, role="methodologist")
    author_b = await make_user(tenant_b, role="methodologist")
    courses = [
        (tenant_a, author_a, await make_course(tenant_a, author_a, title="Filter course A")),
        (tenant_a, author_a, await make_course(tenant_a, author_a, title="Filter course B")),
        (tenant_b, author_b, await make_course(tenant_b, author_b, title="Foreign course C")),
    ]
    requests = []
    for tenant, author, course in courses:
        await set_current_tenant(tenant)
        snapshot = {"course": {"id": str(course.id)}, "modules": []}
        revision = CourseApprovalRevision(
            tenant_id=tenant.id, course_id=course.id, revision_number=1,
            snapshot=snapshot, snapshot_sha256=canonical_json_sha256(snapshot),
            source_fingerprint=canonical_json_sha256(snapshot), created_by=author.id,
        )
        db_session.add(revision)
        await db_session.flush()
        request = CourseApprovalRequest(
            tenant_id=tenant.id, revision_id=revision.id, requested_by=author.id,
            delivery_mode="personal_link",
        )
        db_session.add(request)
        await db_session.flush()
        requests.append(str(request.id))

    headers = auth_headers(author_a)
    for index in (0, 1):
        response = await client.get(
            f"/api/v1/course-approval-requests?course_id={courses[index][2].id}", headers=headers,
        )
        assert response.status_code == 200, response.text
        assert [row["request_id"] for row in response.json()] == [requests[index]]
    foreign = await client.get(
        f"/api/v1/course-approval-requests?course_id={courses[2][2].id}", headers=headers,
    )
    assert foreign.status_code == 200
    assert foreign.json() == []
    legacy = await client.get("/api/v1/course-approval-requests", headers=headers)
    assert legacy.status_code == 200
    assert {row["request_id"] for row in legacy.json()} == set(requests[:2])
