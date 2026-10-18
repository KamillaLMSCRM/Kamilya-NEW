"""Actual async ORM/HTTP serialization and persisted module rename."""
import pytest


@pytest.mark.asyncio
async def test_module_rename_returns_timestamp_and_survives_readback(
    client, make_tenant, make_user, make_course, make_module, auth_headers,
):
    tenant = await make_tenant(name="Module rename QA", slug="module-rename-qa")
    author = await make_user(tenant, role="methodologist", email="module-rename@qa.example")
    course = await make_course(tenant, author, title="Synthetic module rename", status="draft")
    module = await make_module(course, title="Original module")
    response = await client.patch(
        f"/api/v1/modules/{module.id}", json={"title": "Renamed module"},
        headers=auth_headers(author),
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Renamed module"
    assert response.json()["updated_at"]
    structure = await client.get(f"/api/v1/courses/{course.id}/structure", headers=auth_headers(author))
    assert structure.status_code == 200
    assert structure.json()["modules"][0]["id"] == str(module.id)
    assert structure.json()["modules"][0]["title"] == "Renamed module"
