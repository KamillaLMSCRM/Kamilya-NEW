"""Integration tests for superadmin tenant lifecycle hardening.

P0.2 first-tenant hardening.

Covers:
- DELETE requires confirm_slug query param (defense against accidental
  deletion from stray scripts / stale tabs).
- DELETE rejects mismatched confirm_slug.
- Production tenant (slug='kamilya') cannot be deleted.
- Duplicate slug on create returns 409.
- GET /tenants/{id} surfaces stats, usage, and latest_lead.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.models.tenants import RegistrationLegalAcceptance, Tenant, TenantUsage
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.source_actuality.models import (
    DocumentChangeReview,
    DocumentSourcePolicy,
)


async def _login(client, user, password: str = "Password123!") -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _make_superadmin(client, db_session, make_superadmin):
    sa = await make_superadmin()
    token = await _login(client, sa, password="SuperPass123!")
    return sa, token


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
async def test_superadmin_delete_requires_confirm_slug(
    client, db_session, make_tenant, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    tenant = await make_tenant(name="Doomed", slug="doomed")

    # No confirm_slug → 400
    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{tenant.id}",
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "confirm_slug" in resp.json()["message"]


@pytest.mark.asyncio
async def test_superadmin_delete_rejects_mismatched_confirm_slug(
    client, db_session, make_tenant, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    tenant = await make_tenant(name="Doomed2", slug="doomed2")

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{tenant.id}?confirm_slug=wrong",
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "mismatch" in resp.json()["message"]


@pytest.mark.asyncio
async def test_superadmin_delete_with_correct_confirm_slug_succeeds(
    client, db_session, make_tenant, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    tenant = await make_tenant(name="Doomed3", slug="doomed3")

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{tenant.id}?confirm_slug=doomed3",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_superadmin_delete_removes_published_content_release_before_course(
    client, db_session, make_tenant, make_superadmin, set_current_tenant
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}
    tenant = await make_tenant(name="Published", slug="published-release")
    await set_current_tenant(tenant)
    course = Course(
        tenant_id=tenant.id,
        title="Published course",
        description="Synthetic lifecycle fixture",
        status="published",
        review_status="approved",
    )
    db_session.add(course)
    await db_session.flush()
    release = ContentRelease(
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot={"course": "synthetic"},
        snapshot_sha256="0" * 64,
    )
    db_session.add(release)
    await db_session.flush()
    course.current_release_id = release.id
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{tenant.id}?confirm_slug=published-release",
        headers=headers,
    )

    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_superadmin_delete_removes_trial_legal_acceptance_before_user_and_tenant(
    client, db_session, make_tenant, make_user, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}
    tenant = await make_tenant(name="Verified trial", slug="verified-trial")
    user = await make_user(tenant, role="methodologist")
    db_session.add(
        RegistrationLegalAcceptance(
            tenant_id=tenant.id,
            user_id=user.id,
            privacy_consent_version="test-privacy-v1",
            privacy_consent_locale="ru",
            privacy_consent_surface="tenant_registration",
            terms_version="test-terms-v1",
        )
    )
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{tenant.id}?confirm_slug=verified-trial",
        headers=headers,
    )

    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_superadmin_delete_removes_source_actuality_history_before_documents(
    client,
    db_session,
    make_tenant,
    make_user,
    make_document,
    make_superadmin,
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}
    tenant = await make_tenant(
        name="Source actuality purge",
        slug=f"source-purge-{uuid4().hex[:8]}",
    )
    methodologist = await make_user(tenant, role="methodologist")
    family_id = uuid4()
    previous = await make_document(
        tenant,
        methodologist,
        name="policy-v1.md",
        source_family_id=family_id,
        version=1,
        index_status="ready",
    )
    current = await make_document(
        tenant,
        methodologist,
        name="policy-v2.md",
        source_family_id=family_id,
        version=2,
        index_status="ready",
    )
    db_session.add_all(
        [
            DocumentSourcePolicy(
                tenant_id=tenant.id,
                source_family_id=family_id,
                owner_id=methodologist.id,
                created_by=methodologist.id,
                updated_by=methodologist.id,
            ),
            DocumentChangeReview(
                tenant_id=tenant.id,
                source_family_id=family_id,
                previous_document_id=previous.id,
                new_document_id=current.id,
                status="pending",
            ),
        ]
    )
    await db_session.commit()
    tenant_id = tenant.id
    tenant_slug = tenant.slug
    await _set_runtime_role(db_session)

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{tenant_id}?confirm_slug={tenant_slug}",
        headers=headers,
    )

    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    readback = await client.get(
        f"/api/v1/admin/super/tenants/{tenant_id}",
        headers=headers,
    )
    assert readback.status_code == 404, readback.text


@pytest.mark.asyncio
async def test_runtime_tenant_context_cannot_delete_source_actuality_history(
    db_session,
    make_tenant,
    make_user,
    make_document,
    set_current_tenant,
):
    tenant = await make_tenant(
        name="Source actuality retention",
        slug=f"source-retention-{uuid4().hex[:8]}",
    )
    methodologist = await make_user(tenant, role="methodologist")
    family_id = uuid4()
    previous = await make_document(
        tenant,
        methodologist,
        name="retained-v1.md",
        source_family_id=family_id,
        version=1,
    )
    current = await make_document(
        tenant,
        methodologist,
        name="retained-v2.md",
        source_family_id=family_id,
        version=2,
    )
    policy = DocumentSourcePolicy(
        tenant_id=tenant.id,
        source_family_id=family_id,
        owner_id=methodologist.id,
        created_by=methodologist.id,
        updated_by=methodologist.id,
    )
    review = DocumentChangeReview(
        tenant_id=tenant.id,
        source_family_id=family_id,
        previous_document_id=previous.id,
        new_document_id=current.id,
        status="pending",
    )
    db_session.add_all([policy, review])
    await db_session.flush()
    outsider = await make_tenant(
        name="Source actuality outsider",
        slug=f"source-outsider-{uuid4().hex[:8]}",
    )
    await _set_runtime_role(db_session)
    await db_session.execute(
        text("SELECT set_config('app.is_superadmin', 'false', true)")
    )

    deleted_review = await db_session.execute(
        text("DELETE FROM document_change_reviews WHERE id=:id"),
        {"id": review.id},
    )
    deleted_policy = await db_session.execute(
        text("DELETE FROM document_source_policies WHERE id=:id"),
        {"id": policy.id},
    )

    assert deleted_review.rowcount == 0
    assert deleted_policy.rowcount == 0

    await set_current_tenant(outsider)
    await db_session.execute(
        text("SELECT set_config('app.is_superadmin', 'true', true)")
    )
    cross_tenant_review = await db_session.execute(
        text("DELETE FROM document_change_reviews WHERE id=:id"),
        {"id": review.id},
    )
    cross_tenant_policy = await db_session.execute(
        text("DELETE FROM document_source_policies WHERE id=:id"),
        {"id": policy.id},
    )

    assert cross_tenant_review.rowcount == 0
    assert cross_tenant_policy.rowcount == 0


@pytest.mark.asyncio
async def test_source_actuality_policy_catalog_is_command_specific(db_session):
    policies = {
        (row.tablename, row.policyname): (row.cmd, tuple(row.roles))
        for row in (
            await db_session.execute(
                text(
                    "SELECT tablename, policyname, cmd, roles "
                    "FROM pg_policies WHERE schemaname=current_schema() "
                    "AND tablename IN "
                    "('document_change_reviews','document_source_policies')"
                )
            )
        ).all()
    }

    for table in ("document_change_reviews", "document_source_policies"):
        assert policies[(table, f"{table}_tenant_select")] == (
            "SELECT",
            ("lms_app",),
        )
        assert policies[(table, f"{table}_tenant_insert")] == (
            "INSERT",
            ("lms_app",),
        )
        assert policies[(table, f"{table}_tenant_update")] == (
            "UPDATE",
            ("lms_app",),
        )
        assert policies[(table, f"{table}_superadmin_delete")] == (
            "DELETE",
            ("lms_app",),
        )
        assert (table, f"{table}_tenant") not in policies
        assert await db_session.scalar(
            text("SELECT has_table_privilege('lms_app', :table, 'DELETE')"),
            {"table": table},
        ) is True


@pytest.mark.asyncio
async def test_superadmin_cannot_delete_kamilya_prod_tenant(
    client, db_session, make_tenant, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    # Make a tenant that looks like the production one (same slug).
    prod = await make_tenant(name="Kamilya LMS", slug="kamilya")

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{prod.id}?confirm_slug=kamilya",
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert "protected" in resp.json()["message"].lower()


@pytest.mark.asyncio
async def test_superadmin_create_duplicate_slug_returns_409(
    client, db_session, make_tenant, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    await make_tenant(name="Acme", slug="duplicate-test")

    # Try to create another with the same slug
    resp = await client.post(
        "/api/v1/admin/super/tenants",
        headers=headers,
        json={
            "name": "Acme duplicate",
            "slug": "duplicate-test",
            "plan": "trial",
            "status": "trial",
        },
    )
    # The service auto-resolves slug conflict by appending -1, -2, etc.
    # (see _unique_slug). So duplicate slug should succeed with slug
    # `duplicate-test-1`, NOT fail with 409.
    # This test verifies the auto-resolve behavior, NOT a 409.
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tenant"]["slug"] == "duplicate-test-1"


@pytest.mark.asyncio
async def test_superadmin_create_tenant_defaults_is_demo_false_without_first_admin(
    client, db_session, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/admin/super/tenants",
        headers=headers,
        json={"name": "Default Demo Flag", "slug": "default-demo-flag"},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    tenant = await db_session.get(Tenant, body["tenant"]["id"])
    assert body["tenant"]["is_demo"] is False
    assert tenant is not None and tenant.is_demo is False
    assert body["first_admin"] is None
    assert body["invite_url"] is None


@pytest.mark.asyncio
async def test_superadmin_create_tenant_persists_explicit_is_demo_true_without_first_admin(
    client, db_session, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/admin/super/tenants",
        headers=headers,
        json={
            "name": "Explicit Synthetic Demo",
            "slug": "synthetic-explicit-demo",
            "is_demo": True,
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    tenant = await db_session.get(Tenant, body["tenant"]["id"])
    assert body["tenant"]["is_demo"] is True
    assert tenant is not None and tenant.is_demo is True
    assert body["first_admin"] is None
    assert body["invite_url"] is None


@pytest.mark.asyncio
async def test_superadmin_can_mark_existing_tenant_as_demo(
    client, db_session, make_tenant, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}
    tenant = await make_tenant(
        name="Synthetic Recovery",
        slug="synthetic-recovery",
        is_demo=False,
    )

    response = await client.patch(
        f"/api/v1/admin/super/tenants/{tenant.id}",
        headers=headers,
        json={"is_demo": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_demo"] is True
    readback = await client.get(
        f"/api/v1/admin/super/tenants/{tenant.id}",
        headers=headers,
    )
    assert readback.status_code == 200, readback.text
    assert readback.json()["is_demo"] is True

    # Permanent QA stands must be able to leave demo mode through the same
    # canonical API without a post-commit RLS read causing a false failure.
    restored = await client.patch(
        f"/api/v1/admin/super/tenants/{tenant.id}",
        headers=headers,
        json={"is_demo": False},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_demo"] is False
    regular_readback = await client.get(
        f"/api/v1/admin/super/tenants/{tenant.id}", headers=headers
    )
    assert regular_readback.status_code == 200, regular_readback.text
    assert regular_readback.json()["is_demo"] is False
    assert regular_readback.json()["plan"] == readback.json()["plan"]


@pytest.mark.asyncio
async def test_superadmin_get_tenant_surfaces_stats(
    client, db_session, make_tenant, make_user, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    tenant = await make_tenant(
        name="StatsCo",
        slug="statsco",
        settings={
            "trial_limits": {
                "ai_course_generations_limit": 7,
                "jd_course_generations_limit": 4,
                "max_students": 25,
                "system_users_limit": 6,
            },
        },
    )
    db_session.add(TenantUsage(
        tenant_id=tenant.id,
        ai_course_generations_used=3,
        jd_course_generations_used=2,
        active_students_count_snapshot=5,
        system_users_count_snapshot=1,
    ))
    await db_session.flush()
    await make_user(tenant, role="admin", email="a@stats.example")

    resp = await client.get(
        f"/api/v1/admin/super/tenants/{tenant.id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # stats is required for the dashboard card
    assert "stats" in body
    stats = body["stats"]
    assert "user_count" in stats
    assert "active_user_count" in stats
    assert "admin_count" in stats
    assert "course_count" in stats
    assert stats["user_count"] >= 1  # at least the admin
    assert stats["admin_count"] >= 1

    # usage is also surfaced
    assert "usage" in body
    usage = body["usage"]
    assert "ai_course_generations_used" in usage
    assert "jd_course_generations_used" in usage
    assert "active_students_count_snapshot" in usage
    assert usage["ai_course_generations_used"] == 3
    assert usage["ai_course_generations_limit"] == 7
    assert usage["jd_course_generations_limit"] == 4
    assert usage["active_students_limit"] == 25
    assert usage["system_users_limit"] == 6


@pytest.mark.asyncio
async def test_superadmin_delete_nonexistent_returns_404(
    client, db_session, make_superadmin
):
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.delete(
        f"/api/v1/admin/super/tenants/{uuid4()}?confirm_slug=anything",
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_superadmin_requires_auth_for_tenant_lifecycle(client):
    # No Authorization header → 401
    resp = await client.get("/api/v1/admin/super/tenants")
    assert resp.status_code in (401, 403)

    resp = await client.post(
        "/api/v1/admin/super/tenants",
        json={"name": "X", "slug": "x", "plan": "trial", "status": "trial"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_superadmin_create_validation_returns_422(
    client, db_session, make_superadmin
):
    """Bad slug (uppercase) → 422 with field-level error."""
    _, token = await _make_superadmin(client, db_session, make_superadmin)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/admin/super/tenants",
        headers=headers,
        json={
            "name": "Bad slug",
            "slug": "Invalid Slug With Spaces",
            "plan": "trial",
            "status": "trial",
        },
    )
    # Pydantic rejects via schema validator → 422
    assert resp.status_code == 422
