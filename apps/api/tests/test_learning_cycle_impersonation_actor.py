from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.modules.learning_cycles.router import create_rule
from app.modules.learning_cycles.schemas import RuleCreate


class TenantOwnershipDb:
    """Small persistence boundary fake for the public create_rule endpoint."""

    def __init__(self, *, tenant_id: UUID, tenant_author_ids: set[UUID]):
        self.tenant_id = tenant_id
        self.tenant_author_ids = tenant_author_ids
        self.added = []
        self._scalar_calls = 0

    async def scalar(self, _statement):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return uuid4()  # published native course
        if self._scalar_calls == 2:
            return uuid4()  # active tenant student
        raise AssertionError("create_rule queried more than course and learner")

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        assert len(self.added) == 1
        rule = self.added[0]
        assert rule.tenant_id == self.tenant_id
        if rule.created_by is not None:
            assert rule.created_by in self.tenant_author_ids, "created_by must be tenant-owned"


def _body() -> RuleCreate:
    return RuleCreate(course_id=uuid4(), user_id=uuid4(), cadence_days=30, due_days=7)


@pytest.mark.asyncio
async def test_native_rule_create_under_impersonation_uses_nullable_tenant_author():
    tenant_id = uuid4()
    platform_superadmin_id = uuid4()
    db = TenantOwnershipDb(tenant_id=tenant_id, tenant_author_ids=set())
    impersonated = SimpleNamespace(
        id=platform_superadmin_id,
        tenant_id=tenant_id,
        role="methodologist",
        is_impersonating=True,
    )

    rule = await create_rule(_body(), db=db, user=impersonated)

    assert rule is db.added[0]
    assert rule.tenant_id == tenant_id
    assert rule.created_by is None


@pytest.mark.asyncio
async def test_native_rule_create_by_methodologist_preserves_exact_author():
    tenant_id = uuid4()
    methodologist_id = uuid4()
    db = TenantOwnershipDb(tenant_id=tenant_id, tenant_author_ids={methodologist_id})
    methodologist = SimpleNamespace(
        id=methodologist_id,
        tenant_id=tenant_id,
        role="methodologist",
        is_impersonating=False,
    )

    rule = await create_rule(_body(), db=db, user=methodologist)

    assert rule is db.added[0]
    assert rule.tenant_id == tenant_id
    assert rule.created_by == methodologist_id
