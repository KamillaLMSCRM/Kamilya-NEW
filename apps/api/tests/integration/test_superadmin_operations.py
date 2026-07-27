"""P1 tests for superadmin operational observability and safe cleanup."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.ai_job import AIJob
from app.models.document import Document
from app.models.tenants import Tenant
from app.modules.admin.superadmin.operations import CLEANUP_CONFIRM_TOKEN


async def _login(client, user, password: str = "Password123!") -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_operations_summary_is_superadmin_only(client, make_tenant, make_user):
    tenant = await make_tenant(name="Tenant Secret Name", slug="ops-rbac")
    admin = await make_user(
        tenant,
        role="admin",
        email="secret-person@private.example",
    )
    token = await _login(client, admin)

    response = await client.get(
        "/api/v1/admin/super/operations/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_operations_summary_is_aggregate_and_has_no_tenant_pii(
    client, db_session, make_tenant, make_user, make_superadmin
):
    tenant = await make_tenant(name="Tenant Secret Name", slug="ops-summary")
    admin = await make_user(
        tenant,
        role="admin",
        email="secret-person@private.example",
    )
    other_tenant = await make_tenant(name="Other Tenant Name", slug="ops-summary-other")
    other_admin = await make_user(
        other_tenant,
        role="admin",
        email="other-secret@private.example",
    )
    db_session.add(
        AIJob(
            id="ops-summary-job",
            tenant_id=tenant.id,
            user_id=admin.id,
            status="failed",
            stage="failed",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    db_session.add(
        AIJob(
            id="ops-summary-other-job",
            tenant_id=other_tenant.id,
            user_id=other_admin.id,
            status="failed",
            stage="failed",
        )
    )
    db_session.add(
        Document(
            tenant_id=tenant.id,
            uploaded_by=admin.id,
            title="Private document title",
            filename="private.pdf",
            content_type="application/pdf",
            s3_key="synthetic/ops-summary/private.pdf",
            index_status="failed",
            embedding_status="failed",
        )
    )
    await db_session.flush()

    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    response = await client.get(
        "/api/v1/admin/super/operations/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_jobs"]["failed_count"] >= 2
    assert body["documents"]["failed_index_count"] >= 1
    assert body["documents"]["failed_embedding_count"] >= 1
    assert body["database"]["pool_class"]
    assert body["process"]["process_id"] > 0
    assert "Tenant Secret Name" not in response.text
    assert "Other Tenant Name" not in response.text
    assert "secret-person@private.example" not in response.text
    assert "other-secret@private.example" not in response.text
    assert "private.pdf" not in response.text
    assert "Private document title" not in response.text
    assert "message" not in body["ai_jobs"]


@pytest.mark.asyncio
async def test_cleanup_dry_run_matches_only_old_demo_prefixes(
    client, db_session, make_tenant, make_superadmin
):
    old_synthetic = await make_tenant(
        name="Synthetic Old",
        slug="synthetic-old-ops",
        is_demo=True,
    )
    old_synthetic.created_at = datetime.now(UTC) - timedelta(days=3)
    ordinary_prefix = await make_tenant(
        name="Ordinary Prefix",
        slug="synthetic-ordinary-ops",
        is_demo=False,
    )
    ordinary_prefix.created_at = datetime.now(UTC) - timedelta(days=3)
    old_unapproved = await make_tenant(
        name="Unapproved Prefix",
        slug="customer-old-ops",
        is_demo=True,
    )
    old_unapproved.created_at = datetime.now(UTC) - timedelta(days=3)
    young_synthetic = await make_tenant(
        name="Synthetic Young",
        slug="qa-young-ops",
        is_demo=True,
    )
    young_synthetic.created_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.flush()

    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    response = await client.post(
        "/api/v1/admin/super/operations/cleanup-synthetic",
        headers={"Authorization": f"Bearer {token}"},
        json={"min_age_hours": 24},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["deleted_count"] == 0
    assert [item["slug"] for item in body["results"]] == [old_synthetic.slug]
    assert body["results"][0]["action"] == "would_delete"
    assert body["allowed_slug_prefixes"]

    assert await db_session.get(type(old_synthetic), old_synthetic.id) is not None
    assert await db_session.get(type(ordinary_prefix), ordinary_prefix.id) is not None
    assert await db_session.get(type(old_unapproved), old_unapproved.id) is not None
    assert await db_session.get(type(young_synthetic), young_synthetic.id) is not None


@pytest.mark.asyncio
async def test_cleanup_requires_confirmation_for_destructive_mode(
    client, make_superadmin
):
    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    headers = {"Authorization": f"Bearer {token}"}

    for payload in (
        {"dry_run": False},
        {"dry_run": False, "confirm": True, "confirm_token": "wrong"},
    ):
        response = await client.post(
            "/api/v1/admin/super/operations/cleanup-synthetic",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 400, response.text
        assert "confirm" in response.text.lower()


@pytest.mark.asyncio
async def test_cleanup_execute_deletes_only_guarded_tenant(
    client, db_session, make_tenant, make_superadmin
):
    candidate = await make_tenant(
        name="Synthetic To Delete",
        slug="e2e-delete-ops",
        is_demo=True,
    )
    candidate.created_at = datetime.now(UTC) - timedelta(days=2)
    ordinary = await make_tenant(
        name="Ordinary Tenant",
        slug="ordinary-ops",
        is_demo=False,
    )
    ordinary.created_at = datetime.now(UTC) - timedelta(days=2)
    await db_session.flush()
    candidate_id = candidate.id
    ordinary_id = ordinary.id

    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    response = await client.post(
        "/api/v1/admin/super/operations/cleanup-synthetic",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dry_run": False,
            "confirm": True,
            "confirm_token": CLEANUP_CONFIRM_TOKEN,
            "min_age_hours": 24,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted_count"] == 1
    assert body["results"][0]["action"] == "deleted"

    await db_session.rollback()
    candidate_row = (
        await db_session.execute(select(Tenant).where(Tenant.id == candidate_id))
    ).scalar_one_or_none()
    ordinary_row = (
        await db_session.execute(select(Tenant).where(Tenant.id == ordinary_id))
    ).scalar_one_or_none()
    assert candidate_row is None
    assert ordinary_row is not None
