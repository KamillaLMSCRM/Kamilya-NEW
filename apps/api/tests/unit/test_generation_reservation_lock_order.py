"""Tenant-before-job lock ordering for cancellation and retirement."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql.elements import TextClause

from app.modules.ai import job_service, router


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", ["running", "cancelled"])
async def test_cancel_tenant_lock_precedes_job_lock_and_refund(monkeypatch, initial):
    events = []
    tenant = uuid4()
    job = SimpleNamespace(id="job", status=initial, result={}, course_id=None, params={})

    async def tenant_lock(*args):
        events.append("tenant")

    async def get_job(*args, **kwargs):
        events.append("job")
        assert kwargs["for_update"]
        return job

    async def update(*args, **kwargs):
        events.append("update")
        job.status = "cancelled"

    async def release(*args, **kwargs):
        events.append("refund")

    async def commit():
        events.append("commit")

    from app.core import auth

    async def bind_tenant(*args):
        events.append("tenant_context")

    async def bind_user(*args):
        events.append("user_context")

    monkeypatch.setattr(auth, "_set_tenant_security_context", bind_tenant)
    monkeypatch.setattr(auth, "_set_user_security_context", bind_user)
    monkeypatch.setattr(router, "_lock_tenant_row", tenant_lock)
    monkeypatch.setattr(router, "get_ai_job", get_job)
    monkeypatch.setattr(router, "update_ai_job", update)
    monkeypatch.setattr(router, "release_generation_reservation_once", release)
    from app.core.celery_app import celery_app

    monkeypatch.setattr(celery_app.control, "revoke", lambda *a, **k: None)
    result = await router.cancel_generation(
        "job", db=SimpleNamespace(commit=commit), user=SimpleNamespace(id=uuid4(), tenant_id=tenant)
    )
    assert result == {"status": "cancelled"}
    if initial == "running":
        assert events == [
            "tenant",
            "job",
            "update",
            "commit",
            "tenant_context",
            "user_context",
            "tenant",
            "job",
            "refund",
            "commit",
        ]
    else:
        assert events == ["tenant", "job", "tenant_context", "user_context", "tenant", "job", "refund", "commit"]


@pytest.mark.asyncio
async def test_retirement_tenant_lock_before_job_update_and_refund(monkeypatch):
    events = []

    class DB:
        async def execute(self, statement, params=None):
            if isinstance(statement, TextClause):
                events.append("context")
            else:
                events.append("job_update")
            return SimpleNamespace(rowcount=1)

        async def commit(self):
            events.append("commit")

    async def tenant_lock(*args):
        events.append("tenant")

    async def release(*args, **kwargs):
        events.append("refund")

    monkeypatch.setattr(job_service, "_lock_tenant_row", tenant_lock)
    monkeypatch.setattr(job_service, "release_generation_reservation_once", release)
    assert await job_service.retire_legacy_generation_execution(DB(), "job", str(uuid4()), "job")
    assert events == ["context", "tenant", "job_update", "refund", "commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "wrong_status", "refund_missing", "already_refunded", "released"])
async def test_cleanup_rebinds_and_rejects_invisible_or_unreleased_job(monkeypatch, case):
    from app.core import auth

    events = []
    tenant = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant)
    job = SimpleNamespace(
        status="cancelled",
        course_id=None,
        params={"documents": ["source"], "generation_reservation_released": case == "already_refunded"},
    )
    if case == "wrong_status":
        job.status = "running"

    async def bind_tenant(*args):
        events.append("tenant_context")

    async def bind_user(*args):
        events.append("user_context")

    async def lock(*args):
        events.append("tenant_lock")

    async def lookup(*args, **kwargs):
        events.append("job_lock")
        return None if case == "missing" else job

    async def release(*args, **kwargs):
        events.append("refund")
        if case == "released":
            job.params["generation_reservation_released"] = True

    async def commit():
        events.append("commit")

    monkeypatch.setattr(auth, "_set_tenant_security_context", bind_tenant)
    monkeypatch.setattr(auth, "_set_user_security_context", bind_user)
    monkeypatch.setattr(router, "_lock_tenant_row", lock)
    monkeypatch.setattr(router, "get_ai_job", lookup)
    monkeypatch.setattr(router, "release_generation_reservation_once", release)
    if case in ("missing", "wrong_status", "refund_missing"):
        with pytest.raises(ValueError):
            await router._cleanup_cancelled_generation_reservation(SimpleNamespace(commit=commit), "job", user, tenant)
        assert "commit" not in events
    else:
        await router._cleanup_cancelled_generation_reservation(SimpleNamespace(commit=commit), "job", user, tenant)
        assert events == ["tenant_context", "user_context", "tenant_lock", "job_lock", "refund", "commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_reservation", "existing_course"])
async def test_cleanup_non_reserved_or_existing_course_succeeds(monkeypatch, case):
    from app.core import auth

    tenant = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant)
    job = SimpleNamespace(
        status="cancelled",
        course_id=uuid4() if case == "existing_course" else None,
        params={"action": "rewrite"} if case == "no_reservation" else {"documents": ["source"]},
    )

    async def noop(*args, **kwargs):
        pass

    async def lookup(*args, **kwargs):
        return job

    monkeypatch.setattr(auth, "_set_tenant_security_context", noop)
    monkeypatch.setattr(auth, "_set_user_security_context", noop)
    monkeypatch.setattr(router, "_lock_tenant_row", noop)
    monkeypatch.setattr(router, "get_ai_job", lookup)
    monkeypatch.setattr(router, "release_generation_reservation_once", noop)
    await router._cleanup_cancelled_generation_reservation(SimpleNamespace(commit=noop), "job", user, tenant)


@pytest.mark.asyncio
async def test_tenantless_superadmin_scopes_before_cancel_write(monkeypatch):
    from app.core import auth
    from app.core.celery_app import celery_app

    events = []
    tenant = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=None, role="superadmin")
    job = SimpleNamespace(id="job", tenant_id=tenant, status="running", course_id=None, params={}, result={})

    async def lookup(db, job_id, tenant_id=None, for_update=False):
        events.append(("lookup", tenant_id, for_update))
        return job

    async def bind(*a):
        events.append(("bind",))

    async def lock(db, tid):
        events.append(("lock", tid))

    async def update(*a, **kw):
        events.append(("update", kw["tenant_id"]))
        job.status = "cancelled"

    async def release(*a, **kw):
        events.append(("refund", kw["tenant_id"]))

    async def commit():
        events.append(("commit",))

    monkeypatch.setattr(auth, "_set_tenant_security_context", bind)
    monkeypatch.setattr(auth, "_set_user_security_context", bind)
    monkeypatch.setattr(router, "get_ai_job", lookup)
    monkeypatch.setattr(router, "_lock_tenant_row", lock)
    monkeypatch.setattr(router, "update_ai_job", update)
    monkeypatch.setattr(router, "release_generation_reservation_once", release)
    monkeypatch.setattr(celery_app.control, "revoke", lambda *a, **k: None)
    assert await router.cancel_generation("job", db=SimpleNamespace(commit=commit), user=user) == {
        "status": "cancelled"
    }
    assert events[:5] == [
        ("lookup", None, False),
        ("bind",),
        ("bind",),
        ("lock", tenant),
        ("lookup", str(tenant), True),
    ]
    assert ("update", str(tenant)) in events and ("refund", str(tenant)) in events


@pytest.mark.asyncio
async def test_tenantless_missing_scope_never_writes(monkeypatch):
    from fastapi import HTTPException

    events = []

    async def lookup(*a, **kw):
        return SimpleNamespace(tenant_id=None)

    async def write(*a, **kw):
        events.append("write")

    monkeypatch.setattr(router, "get_ai_job", lookup)
    monkeypatch.setattr(router, "update_ai_job", write)
    with pytest.raises(HTTPException):
        await router.cancel_generation(
            "job", db=object(), user=SimpleNamespace(id=uuid4(), tenant_id=None, role="superadmin")
        )
    assert not events
