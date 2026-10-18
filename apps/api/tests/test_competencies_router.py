"""Transaction-boundary tests for competency mutation response DTOs."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.competencies.schemas import CompetencyLinks, CompetencyUpdate


def _item():
    return SimpleNamespace(
        id=uuid4(), name="Safety", description="Old", created_at=datetime.now(UTC),
        position_links=[], course_links=[],
    )


def _user():
    return SimpleNamespace(tenant_id=uuid4())


@pytest.mark.asyncio
async def test_update_materializes_detail_before_commit_readback_is_expired():
    from app.modules.competencies.router import update_competency

    item = _item()
    user = _user()
    db = AsyncMock()
    async def expire_after_commit():
        item.name = None
        item.description = None
    db.commit.side_effect = expire_after_commit

    with patch("app.modules.competencies.router._get", new=AsyncMock(return_value=item)) as get:
        result = await update_competency(
            item.id,
            CompetencyUpdate(name="Updated"),
            db=db,
            user=user,
        )

    assert result.name == "Updated"
    assert result.description == "Old"
    get.assert_awaited_once_with(db, item.id, user.tenant_id)


@pytest.mark.asyncio
async def test_update_binds_lookup_to_the_callers_tenant_and_propagates_commit_failure():
    from app.modules.competencies.router import update_competency

    item = _item()
    user = _user()
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("commit failed")

    with patch("app.modules.competencies.router._get", new=AsyncMock(return_value=item)) as get:
        with pytest.raises(RuntimeError, match="commit failed"):
            await update_competency(item.id, CompetencyUpdate(description="New"), db=db, user=user)

    get.assert_awaited_once_with(db, item.id, user.tenant_id)


@pytest.mark.asyncio
async def test_replace_links_rejects_duplicate_ids_before_any_write():
    from app.modules.competencies.router import replace_links

    item = _item()
    user = _user()
    duplicate = uuid4()
    db = AsyncMock()
    db.add = MagicMock()

    with patch("app.modules.competencies.router._get", new=AsyncMock(return_value=item)):
        with pytest.raises(HTTPException) as exc:
            await replace_links(
                item.id,
                CompetencyLinks(position_ids=[duplicate, duplicate], course_ids=[]),
                db=db,
                user=user,
            )

    assert exc.value.status_code == 422
    assert db.execute.await_count == 0
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_links_rejects_outside_tenant_ids_before_delete_or_commit():
    from app.modules.competencies.router import replace_links

    item = _item()
    outside_position = uuid4()
    db = AsyncMock()
    db.add = MagicMock()
    positions = MagicMock()
    positions.scalars.return_value.all.return_value = []
    db.execute.return_value = positions

    with patch("app.modules.competencies.router._get", new=AsyncMock(return_value=item)):
        with pytest.raises(HTTPException) as exc:
            await replace_links(
                item.id,
                CompetencyLinks(position_ids=[outside_position], course_ids=[]),
                db=db,
                user=_user(),
            )

    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "links_outside_tenant"}
    assert db.execute.await_count == 1
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_links_materializes_new_ids_before_commit():
    from app.modules.competencies.router import replace_links

    item = _item()
    position_id, course_id = uuid4(), uuid4()
    db = AsyncMock()
    db.add = MagicMock()
    positions = MagicMock()
    positions.scalars.return_value.all.return_value = [position_id]
    courses = MagicMock()
    courses.scalars.return_value.all.return_value = [course_id]
    db.execute.side_effect = [positions, courses, MagicMock(), MagicMock()]
    async def expire_after_commit():
        item.position_links = []
        item.course_links = []
    db.commit.side_effect = expire_after_commit

    with patch("app.modules.competencies.router._get", new=AsyncMock(return_value=item)):
        result = await replace_links(
            item.id,
            CompetencyLinks(position_ids=[position_id], course_ids=[course_id]),
            db=db,
            user=_user(),
        )

    assert result.position_ids == [position_id]
    assert result.course_ids == [course_id]
    assert result.position_count == 1
    assert result.course_count == 1
