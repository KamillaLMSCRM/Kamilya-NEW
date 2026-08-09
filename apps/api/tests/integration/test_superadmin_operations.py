"""P1 tests for superadmin operational observability and safe cleanup."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update

from app.models.ai_job import AIJob
from app.models.document import Document
from app.models.tenants import Tenant
from app.modules.admin.superadmin.operations import (
    CLEANUP_CONFIRM_TOKEN,
    CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN,
    STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN,
    SuperadminOperationsService,
)


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

    requeue_response = await client.post(
        "/api/v1/admin/super/operations/requeue-failed-crm-leads",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert requeue_response.status_code == 403


@pytest.mark.asyncio
async def test_crm_outbox_summary_and_bounded_requeue(
    client,
    db_session,
    make_superadmin,
):
    suffix = uuid4().hex
    lead_id = (
        await db_session.execute(
            text(
                "SELECT insert_public_tenant_lead("
                ":company, :contact, :email, NULL, NULL, 'ru', "
                "'demo', NULL, '{}'::jsonb)"
            ),
            {
                "company": "Private CRM Company",
                "contact": "Private CRM Contact",
                "email": f"private-crm-{suffix}@example.test",
            },
        )
    ).scalar_one()
    claimed = (
        await db_session.execute(
            text("SELECT * FROM crm_claim_lead_outbox(:id)"),
            {"id": lead_id},
        )
    ).mappings().one()
    assert (
        await db_session.execute(
            text(
                "SELECT crm_finalize_lead_outbox("
                ":id, :token, 'terminal', 422, 'terminal_http')"
            ),
            {"id": lead_id, "token": claimed["claim_token"]},
        )
    ).scalar_one()

    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    await db_session.execute(
        text("SELECT set_config('app.is_superadmin', 'true', true)")
    )
    summary = (
        await db_session.execute(text("SELECT * FROM crm_lead_outbox_summary()"))
    ).mappings().one()
    assert summary["dead_count"] >= 1
    assert "Private CRM Company" not in str(dict(summary))
    assert f"private-crm-{suffix}@example.test" not in str(dict(summary))

    preview = await client.post(
        "/api/v1/admin/super/operations/requeue-failed-crm-leads",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 1},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True
    assert preview.json()["eligible_count"] == 1
    assert preview.json()["requeued_count"] == 0

    rejected = await client.post(
        "/api/v1/admin/super/operations/requeue-failed-crm-leads",
        headers={"Authorization": f"Bearer {token}"},
        json={"dry_run": False, "limit": 1, "confirm": True},
    )
    assert rejected.status_code == 400

    applied = await client.post(
        "/api/v1/admin/super/operations/requeue-failed-crm-leads",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dry_run": False,
            "limit": 1,
            "confirm": True,
            "confirm_token": CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN,
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["requeued_count"] == 1

    reclaimed = (
        await db_session.execute(
            text("SELECT * FROM crm_claim_lead_outbox(:id)"),
            {"id": lead_id},
        )
    ).mappings().one()
    await db_session.execute(
        text(
            "SELECT crm_finalize_lead_outbox("
            ":id, :token, 'defer', NULL, 'test_cleanup')"
        ),
        {"id": lead_id, "token": reclaimed["claim_token"]},
    )


@pytest.mark.asyncio
async def test_operations_summary_is_aggregate_and_has_no_tenant_pii(
    client, db_session, make_tenant, make_user, make_superadmin, set_current_tenant
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
    await set_current_tenant(tenant)
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
    await db_session.flush()
    await set_current_tenant(other_tenant)
    db_session.add(
        AIJob(
            id="ops-summary-other-job",
            tenant_id=other_tenant.id,
            user_id=other_admin.id,
            status="failed",
            stage="failed",
        )
    )
    await db_session.flush()
    await set_current_tenant(tenant)
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
    assert body["host"]["cpu_percent"] is None or 0 <= body["host"]["cpu_percent"] <= 100
    assert body["process"]["cpu_percent"] is None or body["process"]["cpu_percent"] >= 0
    assert body["process"]["rss_memory_bytes"] is None or body["process"]["rss_memory_bytes"] > 0
    assert body["filesystem"]["total_bytes"] is None or body["filesystem"]["total_bytes"] > 0
    assert body["filesystem"]["free_bytes"] is None or body["filesystem"]["free_bytes"] >= 0
    assert body["filesystem"]["used_percent"] is None or 0 <= body["filesystem"]["used_percent"] <= 100
    assert body["celery"]["status"] in {"available", "unavailable"}
    assert body["celery"]["reachable"] == (body["celery"]["status"] == "available")
    assert "Tenant Secret Name" not in response.text
    assert "Other Tenant Name" not in response.text
    assert "secret-person@private.example" not in response.text
    assert "other-secret@private.example" not in response.text
    assert "private.pdf" not in response.text
    assert "Private document title" not in response.text
    assert "redis://" not in response.text
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


@pytest.mark.asyncio
async def test_stale_ai_job_recovery_is_dry_run_and_ignores_young_and_terminal_jobs(
    client, db_session, make_tenant, make_user, make_superadmin, set_current_tenant
):
    tenant = await make_tenant(name="Synthetic AI Ops", slug="synthetic-ai-ops", is_demo=True)
    user = await make_user(tenant, email="ai-ops@example.test")
    now = datetime.now(UTC)
    old_queued = AIJob(
        id="stale-queued-contract",
        tenant_id=tenant.id,
        user_id=user.id,
        status="pending",
        stage="queued",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    old_running = AIJob(
        id="stale-running-contract",
        tenant_id=tenant.id,
        user_id=user.id,
        status="running",
        stage="generation",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    young = AIJob(
        id="young-running-contract",
        tenant_id=tenant.id,
        user_id=user.id,
        status="running",
        stage="generation",
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
    )
    terminal = AIJob(
        id="terminal-contract",
        tenant_id=tenant.id,
        user_id=user.id,
        status="completed",
        stage="completed",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    await set_current_tenant(tenant)
    db_session.add_all([old_queued, old_running, young, terminal])
    await db_session.flush()

    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    response = await client.post(
        "/api/v1/admin/super/operations/recover-stale-ai-jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"min_age_hours": 24},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["eligible_count"] >= 2
    assert body["queued_count"] >= 1
    assert body["running_count"] >= 1
    assert body["recovered_count"] == 0
    assert body["oldest_age_seconds"] >= 2 * 24 * 3600 - 10
    assert "stale-queued-contract" not in response.text
    assert "ai-ops@example.test" not in response.text

    await set_current_tenant(tenant)
    await db_session.refresh(old_queued)
    await db_session.refresh(old_running)
    await db_session.refresh(young)
    await db_session.refresh(terminal)
    assert old_queued.status == "pending"
    assert old_running.status == "running"
    assert young.status == "running"
    assert terminal.status == "completed"


@pytest.mark.asyncio
async def test_stale_ai_job_recovery_requires_superadmin_confirmation_and_caps_results(
    client,
    db_session,
    make_tenant,
    make_user,
    make_superadmin,
    set_current_tenant,
):
    tenant = await make_tenant(name="Synthetic AI Cap", slug="synthetic-ai-cap", is_demo=True)
    user = await make_user(tenant, email="cap@example.test")
    tenant_id = tenant.id
    user_id = user.id
    # Use the maximum supported age window so unrelated two-day-old fixtures
    # from a shared Supabase test project cannot consume the global cap.
    now = datetime.now(UTC) - timedelta(days=30, hours=1)
    await set_current_tenant(tenant_id)
    for index in range(101):
        db_session.add(
            AIJob(
                id=f"stale-cap-{index}",
                tenant_id=tenant_id,
                user_id=user_id,
                status="pending",
                stage="queued",
                created_at=now,
                updated_at=now,
                message="worker diagnostic retained" if index == 0 else None,
                errors={"worker": "timeout"} if index == 0 else None,
                result={"checkpoint": "retained"} if index == 0 else None,
            )
    )
    await db_session.flush()

    regular = await make_user(
        tenant,
        email="regular@example.com",
        password="UserPass123!",
    )
    regular_token = await _login(client, regular, password="UserPass123!")
    superadmin = await make_superadmin()
    token = await _login(client, superadmin, password="SuperPass123!")
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/admin/super/operations/recover-stale-ai-jobs",
        headers=headers,
        json={"dry_run": False, "min_age_hours": 720, "confirm": True, "confirm_token": "wrong"},
    )
    assert response.status_code == 400, response.text

    with patch.object(
        SuperadminOperationsService,
        "_tenant_ids",
        new=AsyncMock(return_value=[tenant_id]),
    ):
        response = await client.post(
            "/api/v1/admin/super/operations/recover-stale-ai-jobs",
            headers=headers,
            json={
                "dry_run": False,
                "min_age_hours": 720,
                "confirm": True,
                "confirm_token": STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is False
    assert body["terminal_status"] == "cancelled"
    assert body["eligible_count"] == 100
    assert body["recovered_count"] == 100
    assert body["truncated"] is True
    assert "stale-cap-" not in response.text
    assert "cap@example.test" not in response.text
    await db_session.flush()
    await set_current_tenant(tenant_id)
    cancelled_count = (
        await db_session.execute(
            select(AIJob).where(
                AIJob.tenant_id == tenant_id,
                AIJob.status == "cancelled",
                AIJob.id.like("stale-cap-%"),
            )
        )
    ).scalars().all()
    pending_count = (
        await db_session.execute(
            select(AIJob).where(
                AIJob.tenant_id == tenant_id,
                AIJob.status == "pending",
                AIJob.id.like("stale-cap-%"),
            )
        )
    ).scalars().all()
    assert len(cancelled_count) == 100
    assert len(pending_count) == 1

    recovered = (
        await db_session.execute(
            select(AIJob).where(AIJob.id == "stale-cap-0")
        )
    ).scalar_one()
    assert recovered.status == "cancelled"
    assert recovered.stage == "cancelled"
    assert recovered.message.startswith("worker diagnostic retained")
    assert "stale AI job recovery: cancelled" in recovered.message
    assert recovered.errors["previous"] == {"worker": "timeout"}
    assert recovered.errors["recovery"]["code"] == "stale_ai_job_recovered"
    assert recovered.result == {"checkpoint": "retained"}

    late_worker_update = await db_session.execute(
        update(AIJob)
        .where(AIJob.id == "stale-cap-0", AIJob.status != "cancelled")
        .values(status="completed", stage="completed", progress=100)
    )
    assert late_worker_update.rowcount == 0

    response = await client.post(
        "/api/v1/admin/super/operations/recover-stale-ai-jobs",
        headers={"Authorization": f"Bearer {regular_token}"},
        json={"min_age_hours": 720},
    )
    assert response.status_code in {401, 403}
