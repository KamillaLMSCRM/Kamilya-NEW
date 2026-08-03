from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.modules.training_evidence import share_service
from app.modules.training_evidence.models import TrainingEvidenceShare


class _AllowLimiter:
    async def check_rate_limit(self, key: str, limit: int, window: int):
        return True, {"remaining": limit - 1, "reset": 60}


@pytest.mark.asyncio
async def test_public_share_is_tenant_scoped_and_serves_only_immutable_bytes(
    client,
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
    monkeypatch,
):
    tenant_a = await make_tenant(name="Share Tenant A")
    tenant_b = await make_tenant(name="Share Tenant B")
    methodologist = await make_user(tenant_a, role="methodologist")
    await set_current_tenant(tenant_a)

    raw_token = "share-token-a"
    share = TrainingEvidenceShare(
        tenant_id=tenant_a.id,
        token_sha256=hashlib.sha256(raw_token.encode()).hexdigest(),
        package_format="pdf",
        content_type="application/pdf",
        public_filename="kamilya-training-evidence-package.pdf",
        package_bytes=b"immutable-pdf-bytes",
        package_sha256=hashlib.sha256(b"immutable-pdf-bytes").hexdigest(),
        source_event_ids=[str(uuid4())],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_downloads=1,
        created_by_user_id=methodologist.id,
    )
    db_session.add(share)
    await db_session.flush()

    monkeypatch.setattr(share_service, "_public_share_rate_limiter", _AllowLimiter())

    response = await client.get(f"/api/v1/training-evidence/shares/{tenant_a.id}/{raw_token}")
    assert response.status_code == 200
    assert response.content == b"immutable-pdf-bytes"
    assert "kamilya-training-evidence-package.pdf" in response.headers["content-disposition"]
    assert "Share Tenant A" not in response.headers
    assert "methodologist" not in response.headers
    assert "email" not in response.headers
    assert raw_token not in response.headers

    wrong_tenant = await client.get(f"/api/v1/training-evidence/shares/{tenant_b.id}/{raw_token}")
    assert wrong_tenant.status_code == 404
    assert wrong_tenant.json()["error"] == "not_found"
    assert "Share unavailable" in wrong_tenant.json()["message"]

    exhausted = await client.get(f"/api/v1/training-evidence/shares/{tenant_a.id}/{raw_token}")
    assert exhausted.status_code == 404
    assert exhausted.json()["error"] == "not_found"
    assert "Share unavailable" in exhausted.json()["message"]


@pytest.mark.asyncio
async def test_share_row_is_invisible_after_switching_tenant_context(
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="RLS Share Tenant A")
    tenant_b = await make_tenant(name="RLS Share Tenant B")
    user_a = await make_user(tenant_a, role="methodologist")
    await set_current_tenant(tenant_a)
    share = TrainingEvidenceShare(
        tenant_id=tenant_a.id,
        token_sha256=hashlib.sha256(b"rls-token").hexdigest(),
        package_format="zip",
        content_type="application/zip",
        public_filename="kamilya-training-evidence-package.zip",
        package_bytes=b"immutable-zip-bytes",
        package_sha256=hashlib.sha256(b"immutable-zip-bytes").hexdigest(),
        source_event_ids=[str(uuid4())],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_downloads=2,
        created_by_user_id=user_a.id,
    )
    db_session.add(share)
    await db_session.flush()

    # CI seeds fixtures through the database owner. Switch to the restricted
    # production role before the direct visibility assertion so FORCE RLS is
    # exercised instead of being bypassed by the PostgreSQL superuser.
    await db_session.execute(text("SET LOCAL ROLE lms_app"))
    await set_current_tenant(tenant_b)
    visible = await db_session.scalar(
        select(TrainingEvidenceShare).where(TrainingEvidenceShare.id == share.id)
    )
    assert visible is None


@pytest.mark.asyncio
async def test_public_share_integrity_mismatch_returns_404_without_consuming_download(
    client,
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
    monkeypatch,
):
    tenant = await make_tenant(name="Tampered Share Tenant")
    methodologist = await make_user(tenant, role="methodologist")
    await set_current_tenant(tenant)
    raw_token = "tampered-share-token"
    share = TrainingEvidenceShare(
        tenant_id=tenant.id,
        token_sha256=hashlib.sha256(raw_token.encode()).hexdigest(),
        package_format="pdf",
        content_type="application/pdf",
        public_filename="kamilya-training-evidence-package.pdf",
        package_bytes=b"package-that-was-tampered",
        package_sha256=hashlib.sha256(b"different-package").hexdigest(),
        source_event_ids=[str(uuid4())],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_downloads=1,
        created_by_user_id=methodologist.id,
    )
    db_session.add(share)
    await db_session.flush()
    monkeypatch.setattr(share_service, "_public_share_rate_limiter", _AllowLimiter())

    response = await client.get(f"/api/v1/training-evidence/shares/{tenant.id}/{raw_token}")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "Share unavailable" in response.json()["message"]
    assert share.download_count == 0


@pytest.mark.asyncio
async def test_database_rejects_share_created_by_user_from_another_tenant(
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="Share owner tenant A")
    tenant_b = await make_tenant(name="Share owner tenant B")
    foreign_creator = await make_user(tenant_b, role="methodologist")
    await set_current_tenant(tenant_a)

    share = TrainingEvidenceShare(
        tenant_id=tenant_a.id,
        token_sha256=hashlib.sha256(b"foreign-creator-token").hexdigest(),
        package_format="pdf",
        content_type="application/pdf",
        public_filename="kamilya-training-evidence-package.pdf",
        package_bytes=b"bytes",
        package_sha256=hashlib.sha256(b"bytes").hexdigest(),
        source_event_ids=[str(uuid4())],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_downloads=1,
        created_by_user_id=foreign_creator.id,
    )
    savepoint = await db_session.begin_nested()
    try:
        db_session.add(share)
        with pytest.raises(DBAPIError, match="same tenant|foreign key"):
            await db_session.flush()
    finally:
        await savepoint.rollback()


@pytest.mark.asyncio
async def test_database_rejects_access_log_from_another_tenant(
    db_session,
    make_tenant,
    make_user,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="Share log tenant A")
    tenant_b = await make_tenant(name="Share log tenant B")
    creator = await make_user(tenant_a, role="methodologist")
    await set_current_tenant(tenant_a)

    share = TrainingEvidenceShare(
        tenant_id=tenant_a.id,
        token_sha256=hashlib.sha256(b"foreign-log-token").hexdigest(),
        package_format="zip",
        content_type="application/zip",
        public_filename="kamilya-training-evidence-package.zip",
        package_bytes=b"bytes",
        package_sha256=hashlib.sha256(b"bytes").hexdigest(),
        source_event_ids=[str(uuid4())],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_downloads=1,
        created_by_user_id=creator.id,
    )
    db_session.add(share)
    await db_session.flush()

    from app.modules.training_evidence.models import TrainingEvidenceShareAccessLog

    access_log = TrainingEvidenceShareAccessLog(
        tenant_id=tenant_b.id,
        share_id=share.id,
        outcome="downloaded",
        download_count_after=1,
    )
    savepoint = await db_session.begin_nested()
    try:
        db_session.add(access_log)
        with pytest.raises(DBAPIError, match="share tenant|foreign key"):
            await db_session.flush()
    finally:
        await savepoint.rollback()
