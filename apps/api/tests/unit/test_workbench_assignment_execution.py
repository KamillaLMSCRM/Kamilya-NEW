"""Synthetic service/HTTP seam tests; DB locking and RLS need separate gates."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.modules.methodologist_workbench import assignment_router as router_module
from app.modules.methodologist_workbench import assignment_service as service
from app.modules.methodologist_workbench.assignment_models import AssignmentPlan
from app.modules.methodologist_workbench.assignment_schemas import (
    AssignmentPreview,
    AssignmentPreviewRequest,
    Recipient,
)
from app.modules.methodologist_workbench.plan_contract import (
    ActorContext,
    ConfirmationRequest,
    PlanSnapshot,
    plan_fingerprint,
)

NOW = datetime(2026, 10, 1, 10, tzinfo=UTC)


def uid(number: int) -> UUID:
    return UUID(int=number)


def fixture(notify: bool = False):
    actor = ActorContext(tenant_id=uid(2), actor_id=uid(3), active_role="methodologist")
    course = SimpleNamespace(id=uid(4), title="Курс")
    department = SimpleNamespace(id=uid(5), name="Отдел")
    release = SimpleNamespace(id=uid(8), snapshot_sha256="a" * 64)
    recipients = (
        Recipient(user_id=uid(6), label="Новый", already_assigned=False, access_warning=False),
        Recipient(user_id=uid(7), label="Имеющийся", already_assigned=True, access_warning=False),
    )
    binding = (course, department, release, recipients, "b" * 64)
    plan = PlanSnapshot(
        plan_id=uid(1),
        revision=1,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        expires_at=NOW + timedelta(minutes=15),
        operation=service._operation(*binding, NOW + timedelta(days=10), notify),
    )
    preview = AssignmentPreview(
        plan_id=plan.plan_id,
        revision=1,
        fingerprint=plan_fingerprint(plan),
        expires_at=plan.expires_at,
        course_id=course.id,
        course_title=course.title,
        release_id=release.id,
        department_id=department.id,
        department_name=department.name,
        timezone_name="UTC",
        due_at=plan.operation.due_at,
        notify=notify,
        include_descendants=False,
        recipients=recipients,
        new_count=1,
        skipped_count=1,
    )
    row = AssignmentPlan(
        id=plan.plan_id,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        snapshot=plan.model_dump(mode="json"),
        preview=preview.model_dump(mode="json"),
        fingerprint=preview.fingerprint,
        expires_at=plan.expires_at,
        status="ready",
    )
    request = ConfirmationRequest(plan_id=plan.plan_id, revision=1, fingerprint=preview.fingerprint)
    return actor, binding, row, request


@pytest.mark.parametrize("notify", [False, True])
async def test_atomic_result_and_replay_do_not_repeat_enrollment_or_dispatch(monkeypatch, notify):
    actor, binding, row, request = fixture(notify)
    db = SimpleNamespace(scalar=AsyncMock(return_value=row), flush=AsyncMock())
    bindings = AsyncMock(return_value=binding)
    created = SimpleNamespace(user_id=uid(6), id=uid(9), notification_outbox_id=uid(10) if notify else None)
    enroll = AsyncMock(return_value=[created])
    monkeypatch.setattr(service, "_bindings", bindings)
    monkeypatch.setattr(service, "enroll_users", enroll)
    outcome = await service.confirm_assignment_plan(db, actor, request, now=NOW)
    assert row.status == "succeeded" and row.receipt == outcome.receipt.model_dump(mode="json")
    assert outcome.receipt.skipped == (uid(7),)
    assert outcome.dispatch_ids == ((uid(10),) if notify else ())
    assert outcome.receipt.notification_state == ("queued" if notify else "not_requested")
    assert enroll.call_args.kwargs["assigned_by"] == (actor.actor_id if notify else None)
    assert enroll.call_args.kwargs["due_at"] == NOW + timedelta(days=10)
    assert bindings.call_args.kwargs["lock"] is True
    # Replays after expiry still return the committed receipt, no external work.
    replay = await service.confirm_assignment_plan(db, actor, request, now=NOW + timedelta(days=20))
    assert replay.receipt == outcome.receipt and replay.dispatch_ids == ()
    assert enroll.await_count == bindings.await_count == db.flush.await_count == 1


@pytest.mark.parametrize("failure", ["stale", "expired", "wrong_fingerprint", "partial_enrollment"])
async def test_failed_confirmation_does_not_finalize_plan(monkeypatch, failure):
    actor, binding, row, request = fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=row), flush=AsyncMock())
    current = (*binding[:-1], "c" * 64) if failure == "stale" else binding
    monkeypatch.setattr(service, "_bindings", AsyncMock(return_value=current))
    enroll = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "enroll_users", enroll)
    if failure == "wrong_fingerprint":
        request = ConfirmationRequest(plan_id=request.plan_id, revision=1, fingerprint="f" * 64)
    with pytest.raises(service.WorkbenchConflict):
        await service.confirm_assignment_plan(
            db, actor, request, now=NOW + timedelta(hours=1) if failure == "expired" else NOW
        )
    assert row.status == "ready" and row.receipt is None
    assert db.flush.await_count == 0
    assert enroll.await_count == (1 if failure == "partial_enrollment" else 0)


async def test_not_found_and_owner_query_are_tenant_actor_scoped():
    actor, _, _, request = fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(service.WorkbenchNotFound):
        await service.confirm_assignment_plan(db, actor, request, now=NOW)
    statement = db.scalar.call_args.args[0]
    params = set(statement.compile().params.values())
    assert {actor.tenant_id, actor.actor_id, request.plan_id} <= params
    assert statement._for_update_arg is not None


@pytest.mark.parametrize("role", ["admin", "student", "superadmin"])
async def test_service_rejects_inactive_role_before_database(role):
    actor, _, _, request = fixture()
    actor = actor.model_copy(update={"active_role": role})
    db = SimpleNamespace(scalar=AsyncMock())
    with pytest.raises(service.WorkbenchConflict, match="role_denied"):
        await service.confirm_assignment_plan(db, actor, request)
    db.scalar.assert_not_awaited()


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "approved", "recipients", "snapshot"])
def test_preview_transport_rejects_authority(field):
    with pytest.raises(ValidationError):
        AssignmentPreviewRequest.model_validate(
            {
                "instruction": 'Назначь курс "Курс" отделу "Отдел" до 16.10.2026',
                "timezone_name": "UTC",
                field: "forged",
            }
        )


def app_client(monkeypatch, *, role="methodologist", enabled=True, impersonating=False):
    app = FastAPI()
    app.include_router(router_module.router)
    user = SimpleNamespace(id=uid(3), tenant_id=uid(2), role=role, is_impersonating=impersonating)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(router_module, "get_settings", lambda: SimpleNamespace(METHODOLOGIST_WORKBENCH_ENABLED=enabled))
    return TestClient(app), db


@pytest.mark.parametrize(
    ("role", "enabled", "impersonating", "status"),
    [
        ("admin", True, False, 403),
        ("student", True, False, 403),
        ("methodologist", False, False, 404),
        ("methodologist", True, True, 403),
    ],
)
def test_http_role_feature_and_impersonation_gates(monkeypatch, role, enabled, impersonating, status):
    client, db = app_client(monkeypatch, role=role, enabled=enabled, impersonating=impersonating)
    call = AsyncMock()
    monkeypatch.setattr(router_module, "create_assignment_preview", call)
    response = client.post(
        "/methodologist-workbench/assignment-preview", json={"instruction": "test", "timezone_name": "UTC"}
    )
    assert response.status_code == status
    call.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_http_conflict_rolls_back_and_exposes_only_safe_code(monkeypatch):
    client, db = app_client(monkeypatch)
    monkeypatch.setattr(
        router_module, "confirm_assignment_plan", AsyncMock(side_effect=service.WorkbenchConflict("stale"))
    )
    _, _, _, request = fixture()
    response = client.post(
        f"/methodologist-workbench/plans/{request.plan_id}/confirm", json=request.model_dump(mode="json")
    )
    assert response.status_code == 409 and response.json()["detail"] == "stale"
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


def test_http_replay_commits_read_and_does_not_import_dispatch(monkeypatch):
    client, db = app_client(monkeypatch)
    actor, _, row, request = fixture()
    receipt = service.AssignmentReceipt(
        plan_id=request.plan_id, created=(), skipped=(uid(7),), notification_state="not_requested"
    )
    monkeypatch.setattr(
        router_module, "confirm_assignment_plan", AsyncMock(return_value=service.ConfirmationOutcome(receipt, ()))
    )
    response = client.post(
        f"/methodologist-workbench/plans/{request.plan_id}/confirm", json=request.model_dump(mode="json")
    )
    assert response.status_code == 200 and response.json()["state"] == "succeeded"
    assert response.headers["cache-control"] == "no-store"
    db.commit.assert_awaited_once()


def test_mismatched_http_plan_identity_does_not_execute(monkeypatch):
    client, db = app_client(monkeypatch)
    execute = AsyncMock()
    monkeypatch.setattr(router_module, "confirm_assignment_plan", execute)
    _, _, _, request = fixture()
    response = client.post(f"/methodologist-workbench/plans/{uid(99)}/confirm", json=request.model_dump(mode="json"))
    assert response.status_code == 422
    execute.assert_not_awaited()


async def test_position_lock_targets_only_nonnullable_base_table():
    """SQL regression for real PostgreSQL 0A000 caused by eager outer joins."""
    actor, binding, _, _ = fixture()
    course, department, release, _, _ = binding
    course.status = "published"
    course.current_release_id = release.id
    user = SimpleNamespace(
        id=uid(6),
        first_name="Learner",
        last_name="Synthetic",
        has_login_access=True,
        organization_unit_id=department.id,
        position_id=None,
        email=None,
    )
    rows = lambda values: SimpleNamespace(all=lambda: values)  # noqa: E731 - tiny result fixture
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[course, department, release]),
        scalars=AsyncMock(side_effect=[rows([]), rows([]), rows([user]), rows([])]),
    )
    await service._bindings(
        db,
        actor,
        course.id,
        department.id,
        timezone_name="UTC",
        include_descendants=False,
        lock=True,
    )
    position_sql = str(db.scalars.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "LEFT OUTER JOIN departments" in position_sql
    assert "FOR UPDATE OF positions" in position_sql
    user_sql = str(db.scalars.call_args_list[2].args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF users" in user_sql
