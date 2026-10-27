"""Server-paginated staff search remains Unicode-safe and tenant-scoped."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.organization_units import workspace_read

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


class RecordingDb:
    def __init__(self, total: int) -> None:
        self.total = total
        self.count_statements = []
        self.row_statements = []

    async def scalar(self, statement):
        self.count_statements.append(statement)
        return self.total

    async def execute(self, statement):
        self.row_statements.append(statement)
        return SimpleNamespace(all=lambda: [])


async def _search(monkeypatch: pytest.MonkeyPatch, query: str, *, page: int = 1, total: int = 1):
    monkeypatch.setattr(
        workspace_read,
        "workspace_units",
        AsyncMock(return_value={"units": {}, "positions": []}),
    )
    db = RecordingDb(total)
    result = await workspace_read.employee_roster(
        db,
        TENANT_ID,
        unit_id=None,
        unplaced=False,
        scope="subtree",
        access="all",
        q=query,
        position_id=None,
        missing_position=False,
        page=page,
        page_size=20,
    )
    assert len(db.count_statements) == len(db.row_statements) == 1
    return db, result


@pytest.mark.parametrize("query", ["танаб", "ТАНАБ"])
async def test_cyrillic_fragment_uses_explicit_icu_on_both_search_operands(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    db, _result = await _search(monkeypatch, query)

    for statement in (*db.count_statements, *db.row_statements):
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.count('COLLATE "und-x-icu"') == 4
        assert sql.count("lower(") == 4
        assert "ILIKE" not in sql
        assert list(compiled.params.values()).count(f"%{query}%") == 2


async def test_literal_wildcards_stay_escaped_and_filtered_result_resets_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, result = await _search(monkeypatch, " Тест%_\\ ", page=7, total=1)
    statement = db.row_statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    rendered = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert list(compiled.params.values()).count("%Тест\\%\\_\\\\%") == 2
    assert "users.tenant_id" in sql
    assert TENANT_ID in compiled.params.values()
    assert "LIMIT 20" in rendered and "OFFSET 0" in rendered
    assert result == {"items": [], "total": 1, "page": 1, "page_size": 20}
