"""Database-free contracts for position qualification hierarchy handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.positions import qualification_service


@pytest.mark.asyncio
async def test_collect_state_loads_course_rules_from_all_unit_ancestors(monkeypatch):
    tenant_id = uuid4()
    leaf_id = uuid4()
    ancestor_id = uuid4()

    position = type(
        "Position",
        (),
        {
            "tenant_id": tenant_id,
            "id": uuid4(),
            "department_id": leaf_id,
            "instruction_document_id": None,
        },
    )()
    resolve = AsyncMock(return_value=[ancestor_id, leaf_id])
    monkeypatch.setattr(qualification_service, "resolve_ancestor_path", resolve)

    class Result:
        def scalars(self):
            return self

        def all(self):
            return []

    db = AsyncMock()
    db.execute.return_value = Result()
    db.scalar.return_value = None

    await qualification_service._collect_state(db, position)

    resolve.assert_awaited_once_with(db, tenant_id, leaf_id)
    course_queries = [str(call.args[0]) for call in db.execute.await_args_list]
    assert any("department_id" in query for query in course_queries)
    assert any("IN (__[POSTCOMPILE_department_id_1])" in query for query in course_queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("linked", [True, False])
async def test_restore_profile_keeps_current_linked_unit_label(monkeypatch, linked):
    """Restoring a qualification is not a historical HR placement rollback."""
    tenant_id, position_id, actor_id, version_id = (uuid4() for _ in range(4))
    unit_id = uuid4() if linked else None
    position = SimpleNamespace(
        id=position_id, tenant_id=tenant_id, department_id=unit_id,
        department="Current renamed unit", level="Senior", instruction_document_id=None,
    )
    version = SimpleNamespace(snapshot={
        "profile": {"department": "Historical unit label", "level": "Junior"},
    })

    class EmptyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    db = AsyncMock()
    db.scalar.side_effect = [version, None]
    db.execute.return_value = EmptyResult()
    locked = AsyncMock(return_value=position)
    monkeypatch.setattr(qualification_service, "_locked_position", locked)
    monkeypatch.setattr(qualification_service, "_ensure_baseline", AsyncMock())
    monkeypatch.setattr(qualification_service, "_course_map", AsyncMock(return_value={}))
    monkeypatch.setattr(qualification_service, "recompute_position_holders", AsyncMock())
    monkeypatch.setattr(qualification_service, "_mutated_card", AsyncMock(return_value=position))

    restored = await qualification_service.restore(
        db, position_id, version_id, tenant_id, actor_id, "Synthetic restore",
    )

    locked.assert_awaited_once_with(db, position_id, tenant_id)
    assert restored.department == ("Current renamed unit" if linked else "Historical unit label")
    assert restored.department_id == unit_id
    assert restored.level == "Junior"
    # Real restore statements must retain their existing tenant predicates.
    for call in db.execute.await_args_list:
        assert tenant_id in call.args[0].compile().params.values()
