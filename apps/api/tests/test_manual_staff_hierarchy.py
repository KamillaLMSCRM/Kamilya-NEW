from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.department import Department
from app.modules.positions.models import Position
from app.modules.positions.router import _resolve_or_create_department
from app.modules.users.staff_import_router import (
    ManualStaffCreateRequest,
    _resolve_manual_hierarchy,
)


def _payload(**overrides) -> ManualStaffCreateRequest:
    values = {
        "personnel_number": "EMP-001",
        "first_name": "Test",
        "last_name": "Employee",
    }
    values.update(overrides)
    return ManualStaffCreateRequest(**values)


@pytest.mark.asyncio
async def test_position_write_reuses_canonical_department() -> None:
    tenant_id = uuid4()
    department = Department(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Creative",
        slug="creative",
        description="",
    )
    db = AsyncMock()
    db.scalar.return_value = department

    resolved = await _resolve_or_create_department(
        db,
        tenant_id,
        "  Creative  ",
    )

    assert resolved is department
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_manual_hierarchy_uses_canonical_ids() -> None:
    tenant_id = uuid4()
    department = Department(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Creative",
        slug="creative",
        description="",
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Creative Director",
        department=department.name,
        department_id=department.id,
    )
    db = AsyncMock()
    db.scalar.side_effect = [department, position]

    names = await _resolve_manual_hierarchy(
        db,
        tenant_id,
        _payload(department_id=department.id, position_id=position.id),
    )

    assert names == ("Creative", "Creative Director")


@pytest.mark.asyncio
async def test_manual_hierarchy_rejects_position_from_another_department() -> None:
    tenant_id = uuid4()
    selected_department = Department(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Creative",
        slug="creative",
        description="",
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Accountant",
        department="Finance",
        department_id=uuid4(),
    )
    db = AsyncMock()
    db.scalar.side_effect = [selected_department, position]

    with pytest.raises(HTTPException) as error:
        await _resolve_manual_hierarchy(
            db,
            tenant_id,
            _payload(
                department_id=selected_department.id,
                position_id=position.id,
            ),
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "position_department_mismatch"


@pytest.mark.asyncio
async def test_manual_hierarchy_keeps_explicit_new_names() -> None:
    names = await _resolve_manual_hierarchy(
        AsyncMock(),
        uuid4(),
        _payload(department=" New Department ", position=" New Position "),
    )

    assert names == ("New Department", "New Position")
