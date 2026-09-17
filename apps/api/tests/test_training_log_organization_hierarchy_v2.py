"""Database-free contracts for hierarchy-aware training-log projections."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.training_log.repository import _organization_unit_scope
from app.modules.training_log.schemas import TrainingLogRow


@pytest.mark.asyncio
async def test_training_log_scope_delegates_recursive_descendants_to_shared_resolver():
    db = AsyncMock()
    tenant_id, root_id, child_id = uuid4(), uuid4(), uuid4()

    with patch(
        "app.modules.training_log.repository.resolve_descendants",
        new=AsyncMock(return_value={root_id, child_id}),
    ) as resolver:
        result = await _organization_unit_scope(db, tenant_id, root_id)

    assert result == {root_id, child_id}
    resolver.assert_awaited_once_with(db, tenant_id, [root_id], include_self=True, active_only=True)


def test_training_log_row_exposes_current_path_without_breaking_legacy_department_fields():
    unit_id = uuid4()
    row = TrainingLogRow(
        user_id=uuid4(),
        full_name="Employee",
        organization_unit_id=unit_id,
        organization_unit_path=["Central office", "Retail", "Sector A"],
        department_id=unit_id,
        department_name="Sector A",
        position_id=None,
        position_name=None,
        course_id=uuid4(),
        course_title="Course",
        delivery_type="native",
        enrollment_status="enrolled",
        enrollment_source="manual",
        enrollment_id=uuid4(),
        progress_percent=0,
    )

    assert row.organization_unit_id == unit_id
    assert row.organization_unit_path == ["Central office", "Retail", "Sector A"]
    assert row.department_id == unit_id
    assert row.department_name == "Sector A"
