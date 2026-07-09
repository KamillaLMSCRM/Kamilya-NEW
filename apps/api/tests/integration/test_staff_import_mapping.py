"""Integration tests for /api/v1/admin/staff/import/mappings CRUD.

Covers:
- happy path: create, list, get, update, delete
- default flag demotes previous default
- tenant isolation: Tenant A cannot see Tenant B's mappings
- name conflict (409)
- RBAC: student gets 403
- preview/commit accepts mapping_id form field
"""
from __future__ import annotations

from uuid import uuid4

import pytest


async def _login(client, user, password: str = "Password123!") -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


SAMPLE_MAPPING = {
    "personnel_number": "Табельный №",
    "first_name": "Имя",
    "last_name": "Фамилия",
    "department": "Отдел",
    "position": "Должность",
    "email": "Email",
}


@pytest.mark.asyncio
async def test_mappings_requires_auth(client):
    resp = await client.get("/api/v1/admin/staff/import/mappings")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_mappings_student_forbidden(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme", slug="acme-m")
    student = await make_user(tenant, role="student", email="s@m.example")
    token = await _login(client, student)
    resp = await client.get(
        "/api/v1/admin/staff/import/mappings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mappings_create_list_get_delete(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme", slug="acme-m1")
    admin = await make_user(tenant, role="admin", email="a@m1.example")
    token = await _login(client, admin)

    headers = {"Authorization": f"Bearer {token}"}

    # Create
    resp = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "Штатка АО КазМунайГаз", "mapping_json": SAMPLE_MAPPING},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "Штатка АО КазМунайГаз"
    assert created["mapping_json"] == SAMPLE_MAPPING
    assert created["is_default"] is False

    # List
    resp = await client.get("/api/v1/admin/staff/import/mappings", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == created["id"]

    # Get one
    resp = await client.get(
        f"/api/v1/admin/staff/import/mappings/{created['id']}",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Штатка АО КазМунайГаз"

    # Delete
    resp = await client.delete(
        f"/api/v1/admin/staff/import/mappings/{created['id']}",
        headers=headers,
    )
    assert resp.status_code == 204

    # Gone
    resp = await client.get(
        f"/api/v1/admin/staff/import/mappings/{created['id']}",
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mappings_default_flag_demotes_previous(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme", slug="acme-m2")
    admin = await make_user(tenant, role="admin", email="a@m2.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    # First default
    r1 = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "First", "mapping_json": SAMPLE_MAPPING, "is_default": True},
    )
    assert r1.status_code == 201
    first_id = r1.json()["id"]

    # Second default
    r2 = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "Second", "mapping_json": SAMPLE_MAPPING, "is_default": True},
    )
    assert r2.status_code == 201

    # List — Second should be first, First demoted
    resp = await client.get("/api/v1/admin/staff/import/mappings", headers=headers)
    body = resp.json()
    assert body[0]["name"] == "Second"
    assert body[1]["name"] == "First"
    assert body[0]["is_default"] is True
    assert body[1]["is_default"] is False


@pytest.mark.asyncio
async def test_mappings_name_conflict_409(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme", slug="acme-m3")
    admin = await make_user(tenant, role="admin", email="a@m3.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    r1 = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "Dupe", "mapping_json": SAMPLE_MAPPING},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "Dupe", "mapping_json": SAMPLE_MAPPING},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_mappings_tenant_isolation(client, make_tenant, make_user):
    tenant_a = await make_tenant(name="A", slug="a-m")
    tenant_b = await make_tenant(name="B", slug="b-m")
    admin_a = await make_user(tenant_a, role="admin", email="a@a-m.example")
    admin_b = await make_user(tenant_b, role="admin", email="a@b-m.example")

    headers_a = {"Authorization": f"Bearer {await _login(client, admin_a)}"}
    headers_b = {"Authorization": f"Bearer {await _login(client, admin_b)}"}

    r = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers_a,
        json={"name": "A's mapping", "mapping_json": SAMPLE_MAPPING},
    )
    assert r.status_code == 201
    a_id = r.json()["id"]

    # Tenant B sees no mappings
    resp = await client.get("/api/v1/admin/staff/import/mappings", headers=headers_b)
    assert resp.json() == []

    # Tenant B can't read Tenant A's mapping by ID
    resp = await client.get(
        f"/api/v1/admin/staff/import/mappings/{a_id}",
        headers=headers_b,
    )
    assert resp.status_code == 404

    # Tenant B can't delete it
    resp = await client.delete(
        f"/api/v1/admin/staff/import/mappings/{a_id}",
        headers=headers_b,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mappings_update(client, make_tenant, make_user):
    tenant = await make_tenant(name="Acme", slug="acme-m4")
    admin = await make_user(tenant, role="admin", email="a@m4.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "Original", "mapping_json": SAMPLE_MAPPING},
    )
    assert r.status_code == 201
    mapping_id = r.json()["id"]

    # Rename
    r = await client.patch(
        f"/api/v1/admin/staff/import/mappings/{mapping_id}",
        headers=headers,
        json={"name": "Renamed"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"

    # Update mapping_json
    new_mapping = {**SAMPLE_MAPPING, "phone": "Телефон"}
    r = await client.patch(
        f"/api/v1/admin/staff/import/mappings/{mapping_id}",
        headers=headers,
        json={"mapping_json": new_mapping},
    )
    assert r.status_code == 200
    assert r.json()["mapping_json"]["phone"] == "Телефон"


@pytest.mark.asyncio
async def test_preview_accepts_mapping_id_form_field(
    client, db_session, make_tenant, make_user, make_course
):
    """End-to-end: save mapping → use mapping_id in preview."""
    tenant = await make_tenant(name="Acme", slug="acme-m5")
    admin = await make_user(tenant, role="admin", email="a@m5.example")
    token = await _login(client, admin)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/v1/admin/staff/import/mappings",
        headers=headers,
        json={"name": "Saved", "mapping_json": SAMPLE_MAPPING},
    )
    assert r.status_code == 201
    mapping_id = r.json()["id"]

    # Upload a CSV with English headers but mapping says Russian columns
    # — use headers that match the saved mapping values exactly.
    # Use UTF-8 encoded content (csv parser decodes bytes via utf-8).
    csv_content = (
        "Табельный №,Имя,Фамилия,Отдел,Должность,Email\n"
        "123,Иван,Иванов,IT,Developer,ivan@example.com\n"
    ).encode("utf-8")

    resp = await client.post(
        "/api/v1/admin/staff/import/preview",
        headers=headers,
        files={"file": ("staff.csv", csv_content, "text/csv")},
        data={"mapping_id": mapping_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # With mapping applied, no missing columns should be reported
    assert body["missing_required_columns"] == []