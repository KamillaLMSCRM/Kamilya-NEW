from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.learning_actions import service
from app.modules.learning_actions.models import LearningAction, LearningActionEvent
from app.modules.learning_actions.schemas import LearningActionCreate


@pytest.mark.asyncio
async def test_create_persists_intent_and_baseline_without_delivery_side_effects(monkeypatch):
    tenant_id, actor_id, course_id, enrollment_id = (uuid4() for _ in range(4))
    owner_id = actor_id
    row = SimpleNamespace(
        enrollment_id=enrollment_id,
        course_id=course_id,
        computed_status="assigned",
        deadline_status="active",
        progress_percent=0,
        quiz_attempts_count=0,
        best_score=None,
        failed_required_quiz=False,
        completed_at=None,
    )
    monkeypatch.setattr(
        service,
        "_capture_enrollment_snapshot",
        AsyncMock(return_value=(course_id, {"training": {"progress_percent": 0}, "assessment": {"attempt_count": 0}})),
    )
    monkeypatch.setattr(service, "_get_enrollment_row", AsyncMock(return_value=row))
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[owner_id, None]), add=MagicMock(), flush=AsyncMock())
    body = LearningActionCreate(
        target_type="enrollment",
        enrollment_id=enrollment_id,
        issue_type="not_started",
        action_type="reminder",
    )

    result = await service.create_learning_action(db, tenant_id=tenant_id, actor_id=actor_id, body=body)

    assert result.target_key == service.enrollment_target_key(enrollment_id)
    assert result.status == "open"
    assert result.baseline_snapshot["assessment"]["attempt_count"] == 0
    persisted = [call.args[0] for call in db.add.call_args_list]
    assert len(persisted) == 2
    assert isinstance(persisted[0], LearningAction)
    assert isinstance(persisted[1], LearningActionEvent)
    assert persisted[1].event_type == "created"
    assert persisted[1].payload["baseline_snapshot"] == result.baseline_snapshot


@pytest.mark.asyncio
async def test_close_captures_outcome_and_keeps_a_durable_close_event(monkeypatch):
    tenant_id, actor_id, action_id, course_id, enrollment_id = (uuid4() for _ in range(5))
    now = datetime.now(UTC)
    action = LearningAction(
        id=action_id,
        tenant_id=tenant_id,
        target_type="enrollment",
        target_key=service.enrollment_target_key(enrollment_id),
        enrollment_id=enrollment_id,
        course_id=course_id,
        issue_type="not_started",
        action_type="manual_review",
        owner_id=actor_id,
        created_by=actor_id,
        baseline_snapshot={"training": {"progress_percent": 0}},
        status="open",
        created_at=now,
        updated_at=now,
    )
    outcome = {"available": True, "training": {"progress_percent": 100}}
    monkeypatch.setattr(service, "_capture_outcome", AsyncMock(return_value=outcome))
    db = SimpleNamespace(scalar=AsyncMock(return_value=action), add=MagicMock(), flush=AsyncMock())

    result = await service.close_learning_action(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action_id=action_id,
        resolution="observed",
        note=None,
    )

    assert result.status == "completed"
    assert result.resolution == "observed"
    assert result.outcome_snapshot == outcome
    event = db.add.call_args.args[0]
    assert isinstance(event, LearningActionEvent)
    assert event.event_type == "closed"
    assert event.payload["outcome_snapshot"] == outcome


@pytest.mark.asyncio
async def test_observed_close_fails_closed_when_server_cannot_capture_outcome(monkeypatch):
    tenant_id, actor_id, action_id, course_id, enrollment_id = (uuid4() for _ in range(5))
    now = datetime.now(UTC)
    action = LearningAction(
        id=action_id,
        tenant_id=tenant_id,
        target_type="enrollment",
        target_key=service.enrollment_target_key(enrollment_id),
        enrollment_id=enrollment_id,
        course_id=course_id,
        issue_type="not_started",
        action_type="manual_review",
        owner_id=actor_id,
        created_by=actor_id,
        baseline_snapshot={},
        status="open",
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(service, "_capture_outcome", AsyncMock(return_value={"available": False}))
    db = SimpleNamespace(scalar=AsyncMock(return_value=action), add=MagicMock(), flush=AsyncMock())

    with pytest.raises(service.LearningActionConflictError, match="available outcome snapshot"):
        await service.close_learning_action(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action_id=action_id,
            resolution="observed",
            note=None,
        )

    assert action.status == "open"
    db.add.assert_not_called()
