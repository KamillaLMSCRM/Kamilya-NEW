"""Unit-level contract tests for versioned learning programs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.learning_paths.schemas import (
    LearningPathAssignmentAudience,
    LearningPathCreate,
    LearningPathCurriculumReplace,
)
from app.modules.learning_paths.service import path_step_states


def _result(*, one=None, all_rows=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = one
    result.scalars.return_value.unique.return_value.all.return_value = all_rows or []
    result.scalars.return_value.all.return_value = all_rows or []
    return result


def _user(*, role="methodologist", tenant_id=None):
    return SimpleNamespace(id=uuid4(), tenant_id=tenant_id or uuid4(), role=role)


def _path(*, tenant_id, status="draft", courses=None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        family_id=uuid4(),
        version=1,
        title="Onboarding",
        description="",
        status=status,
        sequencing_mode="linear",
        published_at=None,
        created_at=MagicMock(),
        courses=courses or [],
    )


def test_create_schema_is_draft_only_and_curriculum_is_structured():
    assert "status" not in LearningPathCreate.model_fields
    assert "course_ids" not in LearningPathCurriculumReplace.model_fields
    course_id = uuid4()
    payload = LearningPathCurriculumReplace.model_validate(
        {"steps": [{"course_id": str(course_id), "required": False}]}
    )
    assert payload.steps[0].course_id == course_id
    assert payload.steps[0].required is False


def test_linear_sequencing_locks_later_steps_until_required_predecessor_completes():
    first, optional, third = uuid4(), uuid4(), uuid4()
    steps = [
        SimpleNamespace(course_id=first, order_index=0, required=True),
        SimpleNamespace(course_id=optional, order_index=1, required=False),
        SimpleNamespace(course_id=third, order_index=2, required=True),
    ]
    states = path_step_states(steps, set(), "linear")
    assert [item.state for item in states] == ["available", "locked", "locked"]
    states = path_step_states(steps, {first}, "linear")
    assert [item.state for item in states] == ["completed", "available", "available"]


def test_open_sequencing_releases_every_unfinished_step():
    first, second = uuid4(), uuid4()
    steps = [
        SimpleNamespace(course_id=first, order_index=0, required=True),
        SimpleNamespace(course_id=second, order_index=1, required=True),
    ]
    assert [item.state for item in path_step_states(steps, set(), "open")] == ["available", "available"]


def test_published_path_is_rejected_by_draft_guard():
    from app.modules.learning_paths.router import _require_draft

    with pytest.raises(HTTPException) as exc:
        _require_draft(_path(tenant_id=uuid4(), status="published"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "published_version_immutable"


@pytest.mark.asyncio
async def test_publish_requires_nonempty_curriculum():
    from app.modules.learning_paths.router import publish_path

    user = _user()
    path = _path(tenant_id=user.tenant_id, courses=[])
    db = AsyncMock()
    with patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)):
        with pytest.raises(HTTPException) as exc:
            await publish_path(path.id, db=db, user=user)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "curriculum_required"


@pytest.mark.asyncio
async def test_version_clone_requires_published_source_and_creates_next_draft():
    from app.modules.learning_paths.router import create_path_version

    user = _user()
    source = _path(tenant_id=user.tenant_id, status="published")
    source.published_at = MagicMock()
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[None, 1])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    with patch("app.modules.learning_paths.router._get_path", new=AsyncMock(side_effect=[source, source])):
        clone = await create_path_version(source.id, db=db, user=user)
    assert clone.status == "published"  # patched detail lookup returns the source snapshot
    assert db.add.call_count == 1
    created = db.add.call_args.args[0]
    assert created.status == "draft"
    assert created.family_id == source.family_id
    assert created.version == 2
    assert created.supersedes_id == source.id


@pytest.mark.asyncio
async def test_assignment_is_idempotent_for_an_active_matching_user():
    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    existing = SimpleNamespace(user_id=learner_id, status="active")
    db = AsyncMock()
    db.execute.return_value = _result(all_rows=[existing])
    payload = LearningPathAssignmentAudience(user_ids=[learner_id])
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()) as sync,
    ):
        result = await assign_path_audience(path.id, payload, db=db, user=user)
    assert result.added == 0
    assert result.skipped == 1
    assert result.total == 1
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_does_not_resurrect_completed_matching_user():
    from datetime import UTC, datetime

    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    completed_at = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    existing = SimpleNamespace(user_id=learner_id, status="completed", completed_at=completed_at)
    db = AsyncMock()
    db.execute.return_value = _result(all_rows=[existing])
    payload = LearningPathAssignmentAudience(user_ids=[learner_id])
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()) as sync,
    ):
        result = await assign_path_audience(path.id, payload, db=db, user=user)

    assert result.added == 0
    assert result.skipped == 1
    assert result.total == 1
    assert existing.status == "completed"
    assert existing.completed_at == completed_at
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_can_reactivate_cancelled_matching_user():
    from datetime import UTC, datetime

    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    existing = SimpleNamespace(user_id=learner_id, status="cancelled", cancelled_at=uuid4())
    db = AsyncMock()
    db.execute.return_value = _result(all_rows=[existing])
    payload = LearningPathAssignmentAudience(user_ids=[learner_id])
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router._assignment_response",
            return_value=SimpleNamespace(
                id=uuid4(),
                path_id=path.id,
                user_id=learner_id,
                source="manual",
                source_ref_id=None,
                assigned_by=user.id,
                starts_at=None,
                due_at=None,
                status="active",
                created_at=datetime.now(UTC),
                cancelled_at=None,
                completed_at=None,
                user_name=None,
                user_email=None,
            ),
        ),
    ):
        result = await assign_path_audience(path.id, payload, db=db, user=user)

    assert result.added == 1
    assert result.skipped == 0
    assert existing.status == "active"
    assert existing.cancelled_at is None


@pytest.mark.asyncio
async def test_path_lookup_always_contains_tenant_filter():
    from app.modules.learning_paths.router import _get_path

    tenant_id = uuid4()
    path_id = uuid4()
    db = AsyncMock()
    db.execute.return_value = _result(one=_path(tenant_id=tenant_id))
    await _get_path(db, path_id, tenant_id)
    statement = str(db.execute.await_args.args[0])
    assert "learning_paths.tenant_id" in statement


@pytest.mark.asyncio
async def test_learner_query_is_assignment_scoped_not_tenant_catalog_scoped():
    from app.modules.learning_paths.router import list_my_paths

    learner = _user(role="student")
    course_id = uuid4()
    course = SimpleNamespace(id=course_id, title="First course", status="published")
    step = SimpleNamespace(course_id=course_id, course=course, order_index=0, required=True)
    path = _path(tenant_id=learner.tenant_id, status="published", courses=[step])
    assignment = SimpleNamespace(id=uuid4(), path=path, starts_at=None, due_at=None)
    assignments = _result(all_rows=[assignment])
    completed = _result(all_rows=[])
    db = AsyncMock()
    db.execute.side_effect = [assignments, completed]
    with patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()):
        response = await list_my_paths(db=db, user=learner)
    statement = str(db.execute.await_args_list[0].args[0])
    assert "learning_path_assignments" in statement
    assert len(response) == 1
    assert response[0].current_course_id == course_id
