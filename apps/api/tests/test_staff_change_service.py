from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.modules.organization_units.change_service import confirm_change, purge_change_plans
from app.modules.organization_units.workspace_config import staff_workspace_enabled
from app.modules.organization_units.workspace_router import ChangeRequest, ConfirmRequest, is_change_conflict, router


@pytest.mark.asyncio
async def test_expired_plan_cannot_load_or_write_impact():
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = SimpleNamespace(status="ready", expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with patch("app.modules.organization_units.change_service.load_impact_snapshot", new=AsyncMock()) as load:
        with pytest.raises(ValueError, match="preview_expired"):
            await confirm_change(db, tenant_id=uuid4(), actor_id=uuid4(), plan_id=uuid4())
        load.assert_not_called()
    db.add.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_succeeded_receipt_is_replayed_without_current_data_or_expiry_check():
    db = AsyncMock()
    receipt = {"plan_id": str(uuid4()), "status": "succeeded", "added": 2}
    db.scalar.return_value = SimpleNamespace(status="succeeded", receipt=receipt)
    with patch("app.modules.organization_units.change_service.load_impact_snapshot", new=AsyncMock()) as load:
        assert await confirm_change(db, tenant_id=uuid4(), actor_id=uuid4(), plan_id=uuid4()) == receipt
        load.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_owner_plan_not_found_and_stale_plan_writes_nothing():
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = None
    with pytest.raises(LookupError):
        await confirm_change(db, tenant_id=uuid4(), actor_id=uuid4(), plan_id=uuid4())
    db.scalar.return_value = SimpleNamespace(status="ready", expires_at=datetime.now(UTC) + timedelta(minutes=1), fingerprint="old", command={})
    with patch("app.modules.organization_units.change_service.load_impact_snapshot", new=AsyncMock(return_value={"new": True})):
        with pytest.raises(ValueError, match="preview_stale"):
            await confirm_change(db, tenant_id=uuid4(), actor_id=uuid4(), plan_id=uuid4())
    db.add.assert_not_called()
    db.flush.assert_not_called()
    db.execute.assert_not_called()


def test_command_contract_rejects_client_actor_or_replacement_confirm_payload():
    with pytest.raises(ValidationError):
        ChangeRequest(kind="employee", target_id=uuid4(), organization_unit_id=None, reason="Transfer")
    with pytest.raises(ValidationError):
        ChangeRequest(kind="unit", target_id=uuid4(), organization_unit_id=None, reason="Transfer", actor_id=uuid4())
    with pytest.raises(ValidationError):
        ConfirmRequest(confirmed=True, target_id=uuid4())
    assert ConfirmRequest(confirmed=True).confirmed
    paths = {route.path for route in router.routes}
    assert {"/workspace", "/employees", "/changes/preview", "/changes/{plan_id}/confirm"} <= paths


@pytest.mark.parametrize("code,constraint,expected", [
    ("40001", None, True), ("40P01", None, True),
    ("23505", "uq_enrollments_current_occurrence", True),
    ("23505", "other_constraint", False), ("23514", "uq_enrollments_current_occurrence", False),
    ("23505", None, False),
])
def test_only_known_database_races_become_conflicts(code, constraint, expected):
    original = RuntimeError("private database details")
    original.sqlstate = code
    cause = RuntimeError("private database details")
    cause.constraint_name = constraint
    original.__cause__ = cause
    assert is_change_conflict(DBAPIError(None, None, original)) is expected


@pytest.mark.asyncio
async def test_retention_requires_real_database_owner_not_context_flag():
    db = AsyncMock()
    db.scalar.return_value = False
    with pytest.raises(PermissionError, match="maintenance_owner_required"):
        await purge_change_plans(db, uuid4(), dry_run=False)
    db.execute.assert_not_called()
    db.scalars.assert_not_called()
    with pytest.raises(ValueError, match="invalid_retention_batch"):
        await purge_change_plans(db, uuid4(), batch_size=501)


@pytest.mark.parametrize("app_env,contour,flag,expected", [
    ("production", "render-development", True, True),
    ("production", "render-development", False, False),
    ("development", "local", True, True),
    ("test", "local", True, True),
    ("production", "local", True, False),
    ("production", "kz-production", False, False),
    ("production", "kz-production", True, True),
    ("development", "kz-production", True, True),
    ("development", "unknown", True, False),
])
def test_staff_workspace_uses_deployment_contour_without_weakening_runtime(app_env, contour, flag, expected):
    settings = SimpleNamespace(APP_ENV=app_env, DEPLOYMENT_ENVIRONMENT=contour, STAFF_STRUCTURE_V3_ENABLED=flag)
    with patch("app.modules.organization_units.workspace_config.get_settings", return_value=settings):
        assert staff_workspace_enabled() is expected
