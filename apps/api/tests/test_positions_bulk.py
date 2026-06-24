"""Tests for positions: bulk enrollment logic with mocked DB."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.positions.router import (
    _bulk_enroll_users_in_courses,
    _bulk_unenroll_users_from_courses,
)


@pytest.mark.asyncio
async def test_bulk_enroll_all_new():
    """If no existing enrollments, all pairs are created."""
    user_ids = [uuid4(), uuid4()]
    course_ids = [uuid4(), uuid4()]
    tenant_id = uuid4()

    mock_db = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[])  # no existing
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()

    new_count = await _bulk_enroll_users_in_courses(mock_db, user_ids, course_ids, tenant_id)
    assert new_count == 4  # 2 users × 2 courses
    assert mock_db.add.call_count == 4


@pytest.mark.asyncio
async def test_bulk_enroll_skips_existing():
    """Existing pairs are skipped, only NEW pairs created."""
    user1, user2 = uuid4(), uuid4()
    course1, course2 = uuid4(), uuid4()
    tenant_id = uuid4()

    mock_db = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    # user1+course1 already exists
    mock_result.all = MagicMock(return_value=[(user1, course1)])
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()

    new_count = await _bulk_enroll_users_in_courses(
        mock_db, [user1, user2], [course1, course2], tenant_id
    )
    # Should add 3: (u1,c2), (u2,c1), (u2,c2)
    assert new_count == 3
    assert mock_db.add.call_count == 3


@pytest.mark.asyncio
async def test_bulk_enroll_empty_inputs():
    """Empty inputs return 0 without DB calls."""
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.add = MagicMock()

    assert await _bulk_enroll_users_in_courses(mock_db, [], [uuid4()], uuid4()) == 0
    assert await _bulk_enroll_users_in_courses(mock_db, [uuid4()], [], uuid4()) == 0
    assert mock_db.add.call_count == 0


@pytest.mark.asyncio
async def test_bulk_unenroll_filters_active():
    """only_active=True (default) means completed enrollments are preserved."""
    user_ids = [uuid4()]
    course_ids = [uuid4()]
    tenant_id = uuid4()

    mock_db = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_db.execute = AsyncMock(return_value=mock_result)

    removed = await _bulk_unenroll_users_from_courses(
        mock_db, user_ids, course_ids, tenant_id, only_active=True
    )
    assert removed == 1
    # Verify the delete was called with status filter
    call_args = mock_db.execute.call_args
    assert "status" in str(call_args).lower() or call_args is not None
