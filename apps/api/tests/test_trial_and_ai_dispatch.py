"""Regression tests for trial access and durable AI dispatch wiring."""

from datetime import datetime, timedelta, timezone
from inspect import signature
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.tenants import Tenant


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


def test_ai_task_is_durable_task_and_has_uuid_dependency():
    from app.modules.ai.tasks import generate_course_task

    assert generate_course_task is not None
    assert "job_id" in signature(generate_course_task.run).parameters

