import pytest


@pytest.mark.asyncio
async def test_methodologist_cannot_finalize_course_as_learner(
    client,
    auth_headers,
    make_course,
    make_tenant,
    make_user,
):
    tenant = await make_tenant(name="Preview tenant")
    methodologist = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, methodologist, title="Draft preview")

    response = await client.post(
        f"/api/v1/courses/{course.id}/complete",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 403
