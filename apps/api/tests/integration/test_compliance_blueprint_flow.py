"""Tenant and locale flow coverage for compliance blueprint instantiation."""

import pytest

from app.modules.courses.blueprint_catalog import get_blueprint

BLUEPRINT_ID = "kz-occupational-safety-induction"


@pytest.mark.asyncio
async def test_compliance_blueprint_exact_locale_isolated_and_adaptable(
    client,
    auth_headers,
    make_tenant,
    make_user,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="Safety A", slug="compliance-safety-a")
    methodologist_a = await make_user(
        tenant_a,
        role="methodologist",
        email="methodologist@compliance-safety-a.example",
    )
    tenant_b = await make_tenant(name="Safety B", slug="compliance-safety-b")
    methodologist_b = await make_user(
        tenant_b,
        role="methodologist",
        email="methodologist@compliance-safety-b.example",
    )

    await set_current_tenant(tenant_a)
    headers_a = auth_headers(methodologist_a)
    created = await client.post(
        f"/api/v1/course-blueprints/{BLUEPRINT_ID}/instantiate",
        headers=headers_a,
        json={"locale": "kk"},
    )
    assert created.status_code == 201, created.text
    first = created.json()
    course_id_a = first["course_id"]
    assert first["blueprint_id"] == BLUEPRINT_ID
    assert first["locale"] == "kk"
    assert first["readiness_percent"] < 100
    assert first["missing_checklist_items"]

    duplicate = await client.post(
        f"/api/v1/course-blueprints/{BLUEPRINT_ID}/instantiate",
        headers=headers_a,
        json={"locale": "kk"},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["details"]["existing_course_id"] == course_id_a

    await set_current_tenant(tenant_b)
    headers_b = auth_headers(methodologist_b)
    isolated = await client.post(
        f"/api/v1/course-blueprints/{BLUEPRINT_ID}/instantiate",
        headers=headers_b,
        json={"locale": "kk"},
    )
    assert isolated.status_code == 201, isolated.text
    assert isolated.json()["course_id"] != course_id_a

    foreign_adaptation = await client.get(
        f"/api/v1/courses/{course_id_a}/blueprint-adaptation",
        headers=headers_b,
    )
    assert foreign_adaptation.status_code == 404, foreign_adaptation.text

    await set_current_tenant(tenant_a)
    answers = {
        item["id"]: f"Жұмыс тәртібі: {item['id']}"
        for item in get_blueprint("kk", blueprint_id=BLUEPRINT_ID)["checklist"]
    }
    adapted = await client.put(
        f"/api/v1/courses/{course_id_a}/blueprint-adaptation",
        headers=headers_a,
        json={"locale": "kk", "answers": answers},
    )
    assert adapted.status_code == 200, adapted.text
    assert adapted.json()["blueprint_id"] == BLUEPRINT_ID
    assert adapted.json()["locale"] == "kk"
    assert adapted.json()["readiness_percent"] == 100
    assert adapted.json()["missing_checklist_items"] == []
