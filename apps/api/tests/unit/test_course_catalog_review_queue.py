from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.modules.courses import router as courses
from app.modules.source_editorial_review.service import review_queue


@pytest.mark.asyncio
async def test_keep_unpublished_course_with_approval_or_training_history():
    course_id, tenant_id = uuid4(), uuid4()
    course = SimpleNamespace(id=course_id, status="draft", current_release_id=None)
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none = Mock(return_value=course)
    db.scalars.return_value.all = Mock(return_value=[course_id])
    with pytest.raises(HTTPException) as result:
        await courses.delete_course(course_id, Mock(), db, SimpleNamespace(tenant_id=tenant_id))
    assert result.value.status_code == 409
    assert result.value.detail == {"code": "course_archive_required"}
    history = db.scalars.await_args.args[0]
    assert "course_approval_revisions.tenant_id" in str(history)
    assert "enrollments.tenant_id" in str(history)
    assert tenant_id in history.compile().params.values()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_key_conflict", [False, True])
async def test_delete_empty_draft_or_report_new_retained_reference(monkeypatch, foreign_key_conflict):
    course_id, tenant_id = uuid4(), uuid4()
    course = SimpleNamespace(id=course_id, title="Draft", status="draft", current_release_id=None)
    db = AsyncMock()
    db.execute.return_value.scalar_one_or_none = Mock(return_value=course)
    db.scalars.return_value.all = Mock(return_value=[])
    monkeypatch.setattr(courses, "log_action", AsyncMock())
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    if foreign_key_conflict:
        origin = RuntimeError("foreign key")
        origin.sqlstate = "23503"
        db.commit.side_effect = IntegrityError("delete", {}, origin)
        with pytest.raises(HTTPException) as result:
            await courses.delete_course(course_id, Mock(), db, user)
        assert result.value.status_code == 409
        assert result.value.detail["code"] == "course_archive_required"
        db.rollback.assert_awaited_once()
    else:
        await courses.delete_course(course_id, Mock(), db, user)
        db.rollback.assert_not_called()
    db.delete.assert_awaited_once_with(course)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_queue_uses_current_tenant_and_resumable_review_states():
    tenant_id = uuid4()
    first, second = uuid4(), uuid4()
    now = datetime.now(UTC)
    db = AsyncMock()
    db.execute.return_value.all = Mock(return_value=[
        (first, "Procedure awaiting decisions", "answered", now, "a", "a"),
        (second, "Procedure with a stalled check", "queued", now - timedelta(hours=1), "b", "b"),
    ])
    result = await review_queue(db, tenant_id, offset=0, limit=1)
    assert result == {"items": [
        {"document_id": str(first), "title": "Procedure awaiting decisions", "status": "in_review"},
    ], "next_offset": 1}
    statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "document_editorial_events.tenant_id" in str(statement)
    assert "documents.tenant_id" in str(statement)
    assert list(statement.params.values()).count(tenant_id) == 2
