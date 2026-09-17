"""Database-free contracts for position qualification hierarchy handling."""

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
