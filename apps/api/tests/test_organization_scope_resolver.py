"""Tenant-safe tests for the organization_scope deep module."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.organization_scope import (
    resolve_ancestor_path,
    resolve_descendants,
    resolve_employee_scope,
)


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)


class _Db:
    def __init__(self, units):
        self.units = units

    async def execute(self, _statement):
        return _Result(self.units)


def _unit(tenant_id, *, parent_id=None, active=True):
    return SimpleNamespace(id=uuid4(), tenant_id=tenant_id, parent_id=parent_id, is_active=active)


@pytest.mark.asyncio
async def test_descendants_and_ancestors_are_recursive_and_tenant_safe():
    tenant_id, other_tenant = uuid4(), uuid4()
    root = _unit(tenant_id)
    child = _unit(tenant_id, parent_id=root.id)
    leaf = _unit(tenant_id, parent_id=child.id)
    sibling = _unit(tenant_id, parent_id=root.id)
    other_root = _unit(other_tenant)
    other_child = _unit(other_tenant, parent_id=other_root.id)
    db = _Db([root, child, leaf, sibling, other_root, other_child])

    assert await resolve_descendants(db, tenant_id, [root.id]) == {
        root.id,
        child.id,
        leaf.id,
        sibling.id,
    }
    assert await resolve_descendants(db, tenant_id, [root.id], include_self=False) == {
        child.id,
        leaf.id,
        sibling.id,
    }
    assert await resolve_ancestor_path(db, tenant_id, leaf.id) == [root.id, child.id, leaf.id]
    assert await resolve_employee_scope(db, tenant_id, [child.id]) == {child.id, leaf.id}


@pytest.mark.asyncio
async def test_inactive_nodes_are_excluded_from_active_scope():
    tenant_id = uuid4()
    root = _unit(tenant_id)
    inactive_child = _unit(tenant_id, parent_id=root.id, active=False)
    leaf = _unit(tenant_id, parent_id=inactive_child.id)
    db = _Db([root, inactive_child, leaf])

    assert await resolve_descendants(db, tenant_id, [root.id]) == {root.id}
    assert await resolve_descendants(db, tenant_id, [root.id], active_only=False) == {
        root.id,
        inactive_child.id,
        leaf.id,
    }
