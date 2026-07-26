"""Security contracts for department learning-rule course validation."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.departments.router import AttachAllRequest, DepartmentCourseItem


def _department(tenant_id):
    return MagicMock(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Operations",
        slug="operations",
        parent_id=None,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_single_department_attach_rejects_opaque_or_foreign_course_before_binding_write():
    from app.modules.departments.router import attach_course_to_department

    tenant_id = uuid4()
    department = _department(tenant_id)
    user = MagicMock(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    db = AsyncMock()
    db.get = AsyncMock(return_value=department)
    db.scalar = AsyncMock(return_value=None)  # no tenant-published course
    db.add = MagicMock()
    db.flush = AsyncMock()

    with pytest.raises(HTTPException) as caught:
        await attach_course_to_department(
            str(department.id), DepartmentCourseItem(course_id=uuid4()), db, user
        )

    assert caught.value.status_code == 404
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_batch_attach_validates_every_course_before_department_fanout():
    from app.modules.departments.router import attach_courses_to_all_departments

    tenant_id = uuid4()
    user = MagicMock(id=uuid4(), tenant_id=tenant_id, role="methodologist")
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.execute = AsyncMock()

    with pytest.raises(HTTPException) as caught:
        await attach_courses_to_all_departments(
            AttachAllRequest(course_ids=[uuid4()]), db, user
        )

    assert caught.value.status_code == 404
    db.add.assert_not_called()
    db.execute.assert_not_awaited()
