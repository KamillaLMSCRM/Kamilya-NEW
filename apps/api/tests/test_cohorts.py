"""Cohorts are methodologist-owned audience lists, not assignment containers."""

from sqlalchemy import func, select

from app.modules.cohorts.models import CohortCourse, CohortMember
from app.modules.cohorts.router import router


async def test_cohort_is_methodologist_only_and_tenant_scoped(client, make_tenant, make_user, auth_headers):
    tenant_a = await make_tenant(name="Tenant A")
    tenant_b = await make_tenant(name="Tenant B")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    admin_a = await make_user(tenant_a, role="admin")
    methodologist_b = await make_user(tenant_b, role="methodologist")

    created = await client.post(
        "/api/v1/cohorts",
        json={"name": "New hires", "description": "2026 intake"},
        headers=auth_headers(methodologist_a),
    )
    assert created.status_code == 201
    cohort_id = created.json()["id"]

    assert (await client.get("/api/v1/cohorts", headers=auth_headers(admin_a))).status_code == 403
    assert (await client.get(f"/api/v1/cohorts/{cohort_id}", headers=auth_headers(admin_a))).status_code == 403
    assert (await client.get("/api/v1/cohorts", headers=auth_headers(methodologist_b))).json() == []
    assert (await client.get(f"/api/v1/cohorts/{cohort_id}", headers=auth_headers(methodologist_b))).status_code == 404


async def test_cohort_members_are_tenant_scoped_and_courses_are_not_materialized(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant_a = await make_tenant(name="Tenant A")
    tenant_b = await make_tenant(name="Tenant B")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    member_a = await make_user(tenant_a, role="student")
    second_member_a = await make_user(tenant_a, role="student")
    admin_a = await make_user(tenant_a, role="admin")
    member_b = await make_user(tenant_b, role="student")

    created = await client.post("/api/v1/cohorts", json={"name": "Safety"}, headers=auth_headers(methodologist_a))
    cohort_id = created.json()["id"]

    foreign = await client.put(
        f"/api/v1/cohorts/{cohort_id}/members",
        json={"user_ids": [str(member_b.id)]},
        headers=auth_headers(methodologist_a),
    )
    assert foreign.status_code == 422

    non_learner = await client.put(
        f"/api/v1/cohorts/{cohort_id}/members",
        json={"user_ids": [str(admin_a.id)]},
        headers=auth_headers(methodologist_a),
    )
    assert non_learner.status_code == 422

    saved = await client.put(
        f"/api/v1/cohorts/{cohort_id}/members",
        json={"user_ids": [str(member_a.id), str(second_member_a.id)]},
        headers=auth_headers(methodologist_a),
    )
    assert saved.status_code == 200
    assert saved.json()["member_count"] == 2
    assert "course_count" not in saved.json()
    assert await db_session.scalar(select(func.count(CohortMember.id)).where(CohortMember.cohort_id == cohort_id)) == 2
    assert await db_session.scalar(select(func.count(CohortCourse.id)).where(CohortCourse.cohort_id == cohort_id)) == 0

    replaced = await client.put(
        f"/api/v1/cohorts/{cohort_id}/members",
        json={"user_ids": [str(second_member_a.id)]},
        headers=auth_headers(methodologist_a),
    )
    assert replaced.status_code == 200
    assert replaced.json()["member_count"] == 1

    cleared = await client.put(
        f"/api/v1/cohorts/{cohort_id}/members",
        json={"user_ids": []},
        headers=auth_headers(methodologist_a),
    )
    assert cleared.status_code == 200
    assert cleared.json()["member_count"] == 0

    renamed = await client.patch(
        f"/api/v1/cohorts/{cohort_id}",
        json={"name": "Safety 2026", "description": "Updated"},
        headers=auth_headers(methodologist_a),
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Safety 2026"


async def test_legacy_links_endpoint_is_deprecated_and_rejects_course_writes(
    client, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    created = await client.post("/api/v1/cohorts", json={"name": "Legacy client"}, headers=auth_headers(methodologist))
    cohort_id = created.json()["id"]

    rejected = await client.put(
        f"/api/v1/cohorts/{cohort_id}/links",
        json={"user_ids": [], "course_ids": ["00000000-0000-0000-0000-000000000001"]},
        headers=auth_headers(methodologist),
    )
    assert rejected.status_code == 410
    assert rejected.json()["details"]["code"] == "cohort_courses_deprecated"

    empty_compat = await client.put(
        f"/api/v1/cohorts/{cohort_id}/links",
        json={"user_ids": [], "course_ids": []},
        headers=auth_headers(methodologist),
    )
    assert empty_compat.status_code == 200
    assert empty_compat.headers["deprecation"] == "true"


async def test_learner_sees_membership_audience_without_course_contract(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    created = await client.post(
        "/api/v1/cohorts", json={"name": "Learner audience"}, headers=auth_headers(methodologist)
    )
    cohort_id = created.json()["id"]
    await client.put(
        f"/api/v1/cohorts/{cohort_id}/members",
        json={"user_ids": [str(learner.id)]},
        headers=auth_headers(methodologist),
    )

    response = await client.get("/api/v1/cohorts/my", headers=auth_headers(learner))
    assert response.status_code == 200
    assert response.json() == [{"id": cohort_id, "name": "Learner audience", "description": ""}]


def test_cohort_router_has_audience_contract_only():
    paths = {route.path for route in router.routes}
    assert "/cohorts/{cohort_id}/members" in paths
    assert "/cohorts/{cohort_id}/apply" not in paths
    assert "/cohorts/{cohort_id}/progress" not in paths
