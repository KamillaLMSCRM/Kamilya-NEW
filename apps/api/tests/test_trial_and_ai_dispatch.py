"""Regression tests for trial access and durable AI dispatch wiring."""

from datetime import datetime, timedelta, timezone
from inspect import signature
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.tenants import Tenant
from app.models.tenants import TenantUsage


class FakeTenantDB:
    def __init__(self, tenant: Tenant):
        self.tenant = tenant

    async def get(self, model, tenant_id):
        return self.tenant if tenant_id == self.tenant.id else None


def _tenant(**overrides) -> Tenant:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid4(),
        "name": "Trial tenant",
        "slug": f"trial-{uuid4().hex[:8]}",
        "status": "trial",
        "plan": "trial",
        "trial_ends_at": now + timedelta(days=1),
        "paid_until": None,
    }
    values.update(overrides)
    return Tenant(**values)


@pytest.mark.asyncio
async def test_active_trial_allows_tenant_access():
    from app.core.trial_limits import assert_tenant_access

    tenant = _tenant()
    await assert_tenant_access(FakeTenantDB(tenant), tenant.id)


@pytest.mark.asyncio
async def test_expired_trial_returns_machine_readable_error():
    from app.core.trial_limits import assert_tenant_access

    tenant = _tenant(trial_ends_at=datetime.now(timezone.utc) - timedelta(seconds=1))

    with pytest.raises(HTTPException) as caught:
        await assert_tenant_access(FakeTenantDB(tenant), tenant.id)

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "trial_expired"


@pytest.mark.asyncio
async def test_paid_period_overrides_expired_trial():
    from app.core.trial_limits import assert_tenant_access

    tenant = _tenant(
        trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1),
        paid_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    await assert_tenant_access(FakeTenantDB(tenant), tenant.id)


@pytest.mark.asyncio
async def test_suspended_tenant_is_rejected():
    from app.core.trial_limits import assert_tenant_access

    tenant = _tenant(status="suspended")

    with pytest.raises(HTTPException) as caught:
        await assert_tenant_access(FakeTenantDB(tenant), tenant.id)

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "tenant_unavailable"


@pytest.mark.asyncio
async def test_role_gate_checks_trial_access_for_mutations():
    """All role-protected mutation routes share the billing boundary."""
    from app.core.auth import get_current_active_user

    tenant = _tenant(trial_ends_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    user = type("User", (), {"is_active": True, "tenant_id": tenant.id})()

    with pytest.raises(HTTPException) as caught:
        await get_current_active_user(user, FakeTenantDB(tenant))

    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "trial_expired"


@pytest.mark.asyncio
async def test_superadmin_without_tenant_context_bypasses_tenant_policy():
    from app.core.auth import get_current_active_user

    user = type("User", (), {"is_active": True, "tenant_id": None})()
    assert await get_current_active_user(user, FakeTenantDB(_tenant())) is user


def test_ai_task_is_durable_task_and_has_uuid_dependency():
    from app.modules.ai.tasks import generate_course_task

    assert generate_course_task is not None
    assert "job_id" in signature(generate_course_task.run).parameters


class FakeUsageDB:
    def __init__(self, usage: TenantUsage | None = None):
        self.usage = usage
        self.added = None

    async def get(self, model, tenant_id):
        if model is TenantUsage:
            return self.usage
        return None

    def add(self, value):
        self.added = value
        self.usage = value

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_jd_generation_uses_separate_trial_counter(monkeypatch):
    from app.core import trial_limits

    tenant_id = uuid4()
    usage = TenantUsage(tenant_id=tenant_id, jd_course_generations_used=0)
    db = FakeUsageDB(usage)

    async def fake_limits(_db, _tenant_id):
        return trial_limits.TrialLimits(
            jd_course_generations_limit=1,
            max_courses_total=None,
        )

    async def allow_courses(_db, _tenant_id, requested=1):
        return None

    async def allow_tenant(_db, _tenant_id):
        return None

    monkeypatch.setattr(trial_limits, "_get_trial_limits", fake_limits)
    monkeypatch.setattr(trial_limits, "assert_can_create_courses", allow_courses)
    monkeypatch.setattr(trial_limits, "assert_tenant_access", allow_tenant)

    await trial_limits.reserve_jd_course_generation(db, tenant_id)
    assert usage.jd_course_generations_used == 1

    with pytest.raises(HTTPException) as caught:
        await trial_limits.reserve_jd_course_generation(db, tenant_id)

    assert caught.value.status_code == 403
    assert caught.value.detail["resource"] == "jd_courses"

    await trial_limits.release_jd_course_generation(db, tenant_id)
    assert usage.jd_course_generations_used == 0
