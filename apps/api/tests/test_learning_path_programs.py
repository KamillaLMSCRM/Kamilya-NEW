"""Unit-level contract tests for versioned learning programs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.registry import load_all_models
from app.modules.learning_paths.schemas import (
    LearningPathAssignmentAudience,
    LearningPathCreate,
    LearningPathCurriculumReplace,
    LearningPathUpdate,
)
from app.modules.learning_paths.service import (
    path_step_states,
    sync_learning_path_enrollments_after_course_completion,
)


load_all_models()


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


def _completion_assignment(*, tenant_id, status="active"):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=uuid4(),
        path_id=uuid4(),
        status=status,
        starts_at=None,
    )


@pytest.mark.asyncio
async def test_completion_sync_keeps_legacy_integer_result_for_default_callers():
    from app.modules.learning_paths import service

    tenant_id, user_id = uuid4(), uuid4()
    assignment = _completion_assignment(tenant_id=tenant_id)
    db = AsyncMock()
    db.execute.return_value = _result(all_rows=[assignment])
    with patch.object(service, "sync_assignment_enrollments", new=AsyncMock(return_value=2)) as sync:
        result = await sync_learning_path_enrollments_after_course_completion(
            db, tenant_id=tenant_id, user_id=user_id
        )
    assert result == 2
    assert isinstance(result, int)
    sync.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("active", "active", []),
        ("active", "completed", ["transition"]),
        ("completed", "completed", []),
    ],
)
async def test_completion_sync_returns_only_newly_completed_assignments(before, after, expected):
    from app.modules.learning_paths import service

    tenant_id, user_id = uuid4(), uuid4()
    assignment = _completion_assignment(tenant_id=tenant_id, status=before)

    async def sync_one(_db, current, *, now=None):
        current.status = after
        return 0

    db = AsyncMock()
    db.execute.return_value = _result(all_rows=[assignment])
    with patch.object(service, "sync_assignment_enrollments", new=sync_one):
        result = await sync_learning_path_enrollments_after_course_completion(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            return_completed_assignments=True,
        )

    assert ["transition"] if result else [] == expected


def test_assignment_actor_preserves_tenant_user_and_omits_platform_impersonator():
    from app.modules.learning_paths.router import _assignment_actor_id

    tenant_user = _user()
    impersonated_platform_user = _user()
    impersonated_platform_user.is_impersonating = True

    assert _assignment_actor_id(tenant_user) == tenant_user.id
    assert _assignment_actor_id(impersonated_platform_user) is None


def test_create_schema_is_draft_only_and_curriculum_is_structured():
    assert "status" not in LearningPathCreate.model_fields
    assert "course_ids" not in LearningPathCurriculumReplace.model_fields
    course_id = uuid4()
    payload = LearningPathCurriculumReplace.model_validate(
        {"steps": [{"course_id": str(course_id), "required": False}]}
    )
    assert payload.steps[0].course_id == course_id
    assert payload.steps[0].required is False


def test_learning_path_metadata_is_accepted_and_returned_by_schemas():
    responsible_user_id = uuid4()
    create = LearningPathCreate(
        title="Program",
        scenario="onboarding",
        responsible_user_id=responsible_user_id,
        default_due_days=30,
    )
    update = LearningPathUpdate(
        scenario="knowledge_refresh",
        responsible_user_id=responsible_user_id,
        default_due_days=45,
    )

    assert create.model_dump(include={"scenario", "responsible_user_id", "default_due_days"}) == {
        "scenario": "onboarding",
        "responsible_user_id": responsible_user_id,
        "default_due_days": 30,
    }
    assert update.model_dump(exclude_unset=True) == {
        "scenario": "knowledge_refresh",
        "responsible_user_id": responsible_user_id,
        "default_due_days": 45,
    }


@pytest.mark.parametrize("scenario", ["", "unknown", "mandatory-training"])
def test_learning_path_scenario_is_validated(scenario):
    with pytest.raises(ValueError):
        LearningPathCreate(title="Program", scenario=scenario)


@pytest.mark.parametrize("days", [0, 3651])
def test_learning_path_default_due_days_has_bounds(days):
    with pytest.raises(ValueError):
        LearningPathCreate(title="Program", default_due_days=days)


def test_certificate_and_recurrence_policy_schema_accepts_valid_values():
    payload = LearningPathCreate(
        title="Program",
        certificate_mode="final_course",
        certificate_validity_months=12,
        recurrence_mode="fixed_interval_after_completion",
        recurrence_cadence_days=90,
        recurrence_due_days=14,
    )
    assert payload.certificate_mode == "final_course"
    assert payload.certificate_validity_months == 12
    assert payload.recurrence_mode == "fixed_interval_after_completion"
    assert payload.recurrence_cadence_days == 90
    assert payload.recurrence_due_days == 14


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Program", "certificate_mode": "none", "certificate_validity_months": 12},
        {"title": "Program", "recurrence_mode": "none", "recurrence_cadence_days": 30},
        {"title": "Program", "recurrence_mode": "fixed_interval_after_completion"},
        {
            "title": "Program",
            "recurrence_mode": "fixed_interval_after_completion",
            "recurrence_cadence_days": 10,
            "recurrence_due_days": 11,
        },
    ],
)
def test_learning_path_policy_schema_rejects_incoherent_values(payload):
    with pytest.raises(ValueError):
        LearningPathCreate.model_validate(payload)


@pytest.mark.asyncio
async def test_create_path_serializes_certificate_and_recurrence_policy():
    from app.modules.learning_paths.router import create_path

    user = _user()
    payload = LearningPathCreate(
        title="Program",
        certificate_mode="final_course",
        certificate_validity_months=24,
        recurrence_mode="fixed_interval_after_completion",
        recurrence_cadence_days=180,
        recurrence_due_days=30,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    with patch(
        "app.modules.learning_paths.router._detail_then_commit",
        new=AsyncMock(side_effect=lambda _db, path: path),
    ):
        result = await create_path(payload, db=db, user=user)
    created = db.add.call_args.args[0]
    assert (created.certificate_mode, created.certificate_validity_months) == ("final_course", 24)
    assert (created.recurrence_mode, created.recurrence_cadence_days, created.recurrence_due_days) == (
        "fixed_interval_after_completion", 180, 30
    )
    assert result.recurrence_due_days == 30


@pytest.mark.asyncio
async def test_patch_disabling_policies_normalizes_omitted_dependents():
    from app.modules.learning_paths.router import update_path

    user = _user()
    path = _path(tenant_id=user.tenant_id)
    path.certificate_mode = "final_course"
    path.certificate_validity_months = 12
    path.recurrence_mode = "fixed_interval_after_completion"
    path.recurrence_cadence_days = 90
    path.recurrence_due_days = 14
    db = MagicMock()
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch("app.modules.learning_paths.router._detail_then_commit", new=AsyncMock(side_effect=lambda _db, value: value)),
    ):
        await update_path(
            path.id,
            LearningPathUpdate(certificate_mode="none", recurrence_mode="none"),
            db=db,
            user=user,
        )
    assert (path.certificate_mode, path.certificate_validity_months) == ("none", None)
    assert (path.recurrence_mode, path.recurrence_cadence_days, path.recurrence_due_days) == ("none", None, None)


@pytest.mark.asyncio
async def test_create_path_accepts_and_returns_learning_program_metadata():
    from app.modules.learning_paths.router import create_path

    user = _user()
    responsible_user_id = uuid4()
    payload = LearningPathCreate(
        title="Program",
        scenario="onboarding",
        responsible_user_id=responsible_user_id,
        default_due_days=30,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=responsible_user_id)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    with patch(
        "app.modules.learning_paths.router._detail_then_commit",
        new=AsyncMock(side_effect=lambda _db, path: path),
    ):
        result = await create_path(payload, db=db, user=user)

    created = db.add.call_args.args[0]
    assert created.scenario == "onboarding"
    assert created.responsible_user_id == responsible_user_id
    assert created.default_due_days == 30
    assert result.scenario == "onboarding"


@pytest.mark.asyncio
async def test_update_path_accepts_and_returns_learning_program_metadata():
    from app.modules.learning_paths.router import update_path

    user = _user()
    path = _path(tenant_id=user.tenant_id)
    responsible_user_id = uuid4()
    payload = LearningPathUpdate(
        scenario="knowledge_refresh",
        responsible_user_id=responsible_user_id,
        default_due_days=60,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=responsible_user_id)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch("app.modules.learning_paths.router._detail_then_commit", new=AsyncMock(side_effect=lambda _db, value: value)),
    ):
        result = await update_path(path.id, payload, db=db, user=user)

    assert path.scenario == "knowledge_refresh"
    assert path.responsible_user_id == responsible_user_id
    assert path.default_due_days == 60
    assert result is path


@pytest.mark.asyncio
async def test_responsible_user_requires_same_tenant_active_methodologist():
    from app.modules.learning_paths.router import _validate_responsible_user

    tenant_id = uuid4()
    responsible_user_id = uuid4()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await _validate_responsible_user(
            db,
            responsible_user_id=responsible_user_id,
            tenant_id=tenant_id,
        )
    assert exc.value.status_code == 422
    statement = str(db.scalar.await_args.args[0])
    assert "users.id" in statement
    assert "users.tenant_id" in statement
    assert "users.is_active" in statement
    assert "users.status" in statement
    assert "users.role" in statement


@pytest.mark.asyncio
async def test_assignment_explicit_due_at_wins_over_program_default():
    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    path.default_due_days = 30
    explicit_due = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    learner_id = uuid4()
    db = MagicMock()
    db.execute.side_effect = [_result(all_rows=[]), _result(all_rows=[])]
    db.execute = AsyncMock(side_effect=db.execute.side_effect)
    db.add = MagicMock()

    async def flush():
        assignment = db.add.call_args.args[0]
        assignment.id = uuid4()
        assignment.created_at = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)

    db.flush = AsyncMock(side_effect=flush)
    db.commit = AsyncMock()
    payload = LearningPathAssignmentAudience(user_ids=[learner_id], due_at=explicit_due)
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch("app.modules.learning_paths.router._resolve_audience", new=AsyncMock(return_value={learner_id: ("manual", None)})),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await assign_path_audience(path.id, payload, db=db, user=user)

    assert result.assignments[0].due_at == explicit_due


@pytest.mark.asyncio
async def test_assignment_due_at_uses_starts_at_or_current_utc_plus_program_default(monkeypatch):
    from app.modules.learning_paths import router

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    path.default_due_days = 14
    learner_id = uuid4()
    starts_at = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    fixed_now = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)

    async def run(starts):
        db = MagicMock()
        db.execute.side_effect = [_result(all_rows=[]), _result(all_rows=[])]
        db.execute = AsyncMock(side_effect=db.execute.side_effect)
        db.add = MagicMock()

        async def flush():
            assignment = db.add.call_args.args[0]
            assignment.id = uuid4()
            assignment.created_at = fixed_now

        db.flush = AsyncMock(side_effect=flush)
        db.commit = AsyncMock()
        payload = LearningPathAssignmentAudience(user_ids=[learner_id], starts_at=starts)
        with (
            patch.object(router, "_get_path", new=AsyncMock(return_value=path)),
            patch.object(router, "_resolve_audience", new=AsyncMock(return_value={learner_id: ("manual", None)})),
            patch.object(router, "sync_assignment_enrollments", new=AsyncMock()),
            patch.object(
                router,
                "queue_learning_path_assignment_notification",
                new=AsyncMock(return_value=None),
            ),
            patch.object(router, "datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = fixed_now
            datetime_mock.side_effect = datetime
            result = await router.assign_path_audience(path.id, payload, db=db, user=user)
        return result.assignments[0].due_at

    assert await run(starts_at) == starts_at + timedelta(days=14)
    assert await run(None) == fixed_now + timedelta(days=14)


@pytest.mark.asyncio
async def test_new_version_preserves_learning_program_metadata():
    from app.modules.learning_paths.router import create_path_version

    user = _user()
    source = _path(tenant_id=user.tenant_id, status="published")
    source.scenario = "process_update"
    source.responsible_user_id = uuid4()
    source.default_due_days = 21
    source.certificate_mode = "final_course"
    source.certificate_validity_months = 6
    source.recurrence_mode = "fixed_interval_after_completion"
    source.recurrence_cadence_days = 60
    source.recurrence_due_days = 10
    source.published_at = MagicMock()
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[None, 1])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    with patch("app.modules.learning_paths.router._get_path", new=AsyncMock(side_effect=[source, source])):
        await create_path_version(source.id, db=db, user=user)
    clone = db.add.call_args.args[0]
    assert clone.scenario == source.scenario
    assert clone.responsible_user_id == source.responsible_user_id
    assert clone.default_due_days == source.default_due_days
    assert clone.certificate_mode == source.certificate_mode
    assert clone.certificate_validity_months == source.certificate_validity_months
    assert clone.recurrence_mode == source.recurrence_mode
    assert clone.recurrence_cadence_days == source.recurrence_cadence_days
    assert clone.recurrence_due_days == source.recurrence_due_days


def test_legacy_learning_path_without_metadata_serializes_with_defaults():
    from app.modules.learning_paths.router import _summary

    summary = _summary(_path(tenant_id=uuid4()))
    assert summary.scenario == "custom"
    assert summary.responsible_user_id is None
    assert summary.default_due_days is None


@pytest.mark.asyncio
async def test_learning_path_detail_is_built_before_transaction_commit(monkeypatch):
    from app.modules.learning_paths import router

    events: list[str] = []
    path = _path(tenant_id=uuid4())
    expected = object()

    class RecordingSession:
        async def flush(self):
            events.append("flush")

        async def commit(self):
            events.append("commit")

    async def get_path(db, path_id, tenant_id):
        assert path_id == path.id
        assert tenant_id == path.tenant_id
        events.append("get")
        return path

    def build_detail(value):
        assert value is path
        events.append("detail")
        return expected

    monkeypatch.setattr(router, "_get_path", get_path)
    monkeypatch.setattr(router, "_detail", build_detail)

    result = await router._detail_then_commit(RecordingSession(), path)

    assert result is expected
    assert events == ["flush", "get", "detail", "commit"]


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
    enqueue = AsyncMock()
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()) as sync,
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=enqueue,
        ),
    ):
        result = await assign_path_audience(path.id, payload, db=db, user=user)
    assert result.added == 0
    assert result.skipped == 1
    assert result.total == 1
    sync.assert_not_awaited()
    enqueue.assert_not_awaited()


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
    enqueue = AsyncMock()
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()) as sync,
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=enqueue,
        ),
    ):
        result = await assign_path_audience(path.id, payload, db=db, user=user)

    assert result.added == 0
    assert result.skipped == 1
    assert result.total == 1
    assert existing.status == "completed"
    assert existing.completed_at == completed_at
    sync.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_can_reactivate_cancelled_matching_user():
    from datetime import UTC, datetime

    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    assignment_id = uuid4()
    existing = SimpleNamespace(
        id=assignment_id,
        tenant_id=user.tenant_id,
        path_id=path.id,
        user_id=learner_id,
        source="manual",
        source_ref_id=None,
        assigned_by=user.id,
        starts_at=None,
        due_at=None,
        status="cancelled",
        cancelled_at=uuid4(),
        completed_at=None,
        recurrence_instance_id=None,
    )
    db = AsyncMock()
    db.execute.return_value = _result(all_rows=[existing])
    payload = LearningPathAssignmentAudience(user_ids=[learner_id])
    notification_id = uuid4()
    enqueue = AsyncMock(return_value=notification_id)
    dispatch = MagicMock()
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=enqueue,
        ),
        patch(
            "app.modules.enrollments.notification_tasks.deliver_assignment_notification_task.apply_async",
            new=dispatch,
        ),
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
    enqueue.assert_awaited_once_with(
        db,
        tenant_id=user.tenant_id,
        learning_path_assignment_id=assignment_id,
        assigned_by=user.id,
    )
    dispatch.assert_called_once_with(
        args=[str(user.tenant_id), str(notification_id)],
        kwargs={"notification_kind": "learning_path"},
    )


def _new_assignment_db(*, commit_side_effect=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(all_rows=[]))
    db.add = MagicMock()

    async def flush():
        assignment = db.add.call_args.args[0]
        assignment.id = uuid4()
        assignment.created_at = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)

    db.flush = AsyncMock(side_effect=flush)
    db.commit = AsyncMock(side_effect=commit_side_effect)
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_new_assignment_enqueues_once_then_dispatches_after_commit():
    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    notification_id = uuid4()
    events: list[str] = []
    db = _new_assignment_db(commit_side_effect=lambda: events.append("commit"))

    async def enqueue(*args, **kwargs):
        assert db.commit.await_count == 0
        events.append("enqueue")
        return notification_id

    dispatch = MagicMock(side_effect=lambda **_kwargs: events.append("dispatch"))
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=AsyncMock(side_effect=enqueue),
        ) as enqueue_mock,
        patch(
            "app.modules.enrollments.notification_tasks.deliver_assignment_notification_task.apply_async",
            new=dispatch,
        ),
    ):
        result = await assign_path_audience(
            path.id,
            LearningPathAssignmentAudience(user_ids=[learner_id]),
            db=db,
            user=user,
        )

    assignment = db.add.call_args.args[0]
    assert result.added == 1
    assert result.skipped == 0
    assert db.commit.await_count == 1
    enqueue_mock.assert_awaited_once_with(
        db,
        tenant_id=user.tenant_id,
        learning_path_assignment_id=assignment.id,
        assigned_by=user.id,
    )
    dispatch.assert_called_once_with(
        args=[str(user.tenant_id), str(notification_id)],
        kwargs={"notification_kind": "learning_path"},
    )
    assert events == ["enqueue", "commit", "dispatch"]


@pytest.mark.asyncio
async def test_failed_assignment_commit_never_dispatches_notification():
    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    db = _new_assignment_db(commit_side_effect=RuntimeError("commit failed"))
    dispatch = MagicMock()
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=AsyncMock(return_value=uuid4()),
        ),
        patch(
            "app.modules.enrollments.notification_tasks.deliver_assignment_notification_task.apply_async",
            new=dispatch,
        ),
    ):
        with pytest.raises(RuntimeError, match="commit failed"):
            await assign_path_audience(
                path.id,
                LearningPathAssignmentAudience(user_ids=[learner_id]),
                db=db,
                user=user,
            )

    assert db.commit.await_count == 1
    dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_failure_keeps_successful_assignment_response_and_does_not_rollback(caplog):
    from app.modules.learning_paths.router import assign_path_audience

    user = _user()
    path = _path(tenant_id=user.tenant_id, status="published")
    learner_id = uuid4()
    notification_id = uuid4()
    db = _new_assignment_db()
    dispatch = MagicMock(side_effect=RuntimeError("broker unavailable"))
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=AsyncMock(return_value=notification_id),
        ),
        patch(
            "app.modules.enrollments.notification_tasks.deliver_assignment_notification_task.apply_async",
            new=dispatch,
        ),
    ):
        result = await assign_path_audience(
            path.id,
            LearningPathAssignmentAudience(user_ids=[learner_id]),
            db=db,
            user=user,
        )

    assert result.added == 1
    assert result.skipped == 0
    assert db.commit.await_count == 1
    db.rollback.assert_not_awaited()
    assert "durable outbox recovery will retry" in caplog.text
    assert "learner" not in caplog.text.lower()


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
