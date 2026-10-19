from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.organization_units import change_service, workspace_read


@pytest.mark.parametrize("size", [50, 1000, 5000])
@pytest.mark.parametrize("wide", [True, False])
async def test_overview_rollups_walk_each_unit_path_once(monkeypatch, size, wide):
    units = {str(i): {"id": str(i), "name": str(i), "parent_id": None if i == 0 else
        "0" if wide else str((i - 1) // 10), "source_metadata": {}}
        for i in range(size)}
    data = {"units": units, "positions": [{"id": "p"}]}
    monkeypatch.setattr(workspace_read, "workspace_units", AsyncMock(return_value=data))
    walk = Mock(wraps=workspace_read.ancestor_ids)
    monkeypatch.setattr(workspace_read, "ancestor_ids", walk)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(all=lambda: [(str(i), 1) for i in range(size)]),
        SimpleNamespace(all=lambda: [("p", str(i), 1) for i in range(size)]),
    ]))
    result = await workspace_read.workspace_overview(db, UUID(int=1), "all")
    assert walk.call_count == size  # deterministic complexity, no flaky time threshold
    assert db.execute.await_count == 2
    assert result["total"] == size
    assert result["units"][0]["subtree_count"] == size
    assert result["positions"][0]["employee_count"] == size
    assert result["units"][-1]["direct_count"] == 1


async def test_employee_impact_load_scopes_large_history_before_safety_limit(monkeypatch):
    tenant, employee = UUID(int=1), UUID(int=2)
    seen = []
    class Result:
        def mappings(self):
            return self
        def all(self):
            return []
    async def execute(statement):
        seen.append(statement)
        return Result()
    await change_service.load_impact_snapshot(SimpleNamespace(execute=execute), tenant,
        command={"kind": "employee", "target_id": str(employee), "organization_unit_id": None})
    queries = [s for s in seen if "FROM enrollments" in str(s)]
    assert len(queries) == 1
    query = queries[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "enrollments.tenant_id" in sql and "enrollments.user_id IN" in sql
    assert str(employee) in sql and "LIMIT 25001" in sql
    # 25k unrelated enrollments never enter the snapshot; relevant over-limit
    # rows still fail closed rather than producing an incomplete preview.


async def test_relevant_snapshot_safety_ceiling_remains_fail_closed():
    class Result:
        def mappings(self):
            return self
        def all(self):
            return [{"id": UUID(int=i + 1)} for i in range(25001)]
    from app.models.enrollment import Enrollment
    db = SimpleNamespace(execute=AsyncMock(return_value=Result()))
    with pytest.raises(ValueError, match="impact_snapshot_too_large"):
        await change_service._rows(db, Enrollment, UUID(int=1), ("id",))
