"""Reproduce actual import/purge seams; no external database or Redis needed."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.department import Department
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.admin.superadmin.service import SuperadminService
from app.modules.positions.models import Position
from app.modules.users.staff_import_service import ParsedFile, ParsedRow, commit_import


class TransactionScopedDb:
    """Model transaction-local RLS expiry; actual recompute/resolver are not stubbed."""
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.context = tenant_id
        self.rows = []
        self.events = []

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        for row in self.rows:
            if isinstance(row, Department | Position) and row.is_active is None:
                row.is_active = True
            if isinstance(row, Position) and row.employee_count is None:
                row.employee_count = 0

    async def commit(self):
        self.events.append("commit")
        self.context = None

    async def get(self, model, identity):
        # SQLAlchemy expire_on_commit=False retains already-materialized objects.
        return next((row for row in self.rows if isinstance(row, model) and row.id == identity), None)

    async def execute(self, statement, params=None):
        if "set_current_tenant" in str(statement):
            assert params == {"tid": str(self.tenant_id)}
            self.context = self.tenant_id
            self.events.append("restore")
            return MagicMock()
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        rows = [row for row in self.rows if entity in (Department, Position, User)
                and isinstance(row, entity) and self.context == self.tenant_id]
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        result.all.return_value = []
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_changes", [True, False])
async def test_import_real_recompute_preserves_active_department_after_commit(commit_changes):
    tenant_id = uuid4()
    db = TransactionScopedDb(tenant_id)
    parsed = ParsedFile(rows=[ParsedRow(row_number=2, personnel_number="CAP-TEST-001",
                        first_name="Synthetic", last_name="Learner", department="Synthetic department",
                        position="Synthetic position")], total_rows_in_file=1,
                        invalid_rows=[], detected_columns={}, missing_required_columns=[])
    success, failure = AsyncMock(), AsyncMock()
    with (patch("app.core.redis_progress.new_task_id", return_value="synthetic-task"),
          patch("app.core.redis_progress.init_task", new=AsyncMock()),
          patch("app.core.redis_progress.mark_started", new=AsyncMock()),
          patch("app.core.redis_progress.increment_done", new=AsyncMock()),
          patch("app.core.redis_progress.increment_failed", new=AsyncMock()),
          patch("app.core.redis_progress.mark_success", success),
          patch("app.core.redis_progress.mark_failure", failure)):
        result = await commit_import(db, tenant_id, parsed, commit_changes=commit_changes)
    assert result["created"] == 1 and result["positions_created"] == 1
    success.assert_awaited_once()
    failure.assert_not_awaited()
    assert success.await_args.args[1]["users_processed"] == 1
    assert success.await_args.args[1]["added"] == success.await_args.args[1]["removed"] == 0
    department = next(row for row in db.rows if isinstance(row, Department))
    position = next(row for row in db.rows if isinstance(row, Position))
    assert department.is_active and position.department_id == department.id
    assert db.context == tenant_id
    if commit_changes:
        assert db.events == ["commit", "restore"]
    else:
        assert db.events == []


@pytest.mark.asyncio
async def test_actual_tenant_purge_deletes_positions_before_departments_and_tenant():
    tenant_id = uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=Tenant(id=tenant_id, name="Synthetic", slug="capacity-synthetic",
                                          status="active", plan="enterprise", settings={}))
    db.commit = AsyncMock()
    events = []
    async def execute(statement, params=None):
        sql = str(statement).strip()
        if "information_schema.columns" in sql:
            return [(table, "tenant_id") for table in ("users", "positions", "departments", "tenants")]
        if sql.startswith("DELETE FROM"):
            assert params == {"tenant_id": str(tenant_id)}
            events.append(sql.split()[2])
        return MagicMock()
    db.execute = AsyncMock(side_effect=execute)
    await SuperadminService(db).delete_tenant(tenant_id)
    assert events == ["users", "positions", "departments", "tenants"]
    db.commit.assert_awaited_once()
