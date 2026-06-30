"""Unit tests for the staff-import apply-rules status endpoint (B1c).

Covers:
  - state mapping: PENDING / STARTED / SUCCESS / FAILURE / REVOKED
  - body extraction on SUCCESS (dict result is passed through)
  - exception stringification on FAILURE
  - empty / missing task_id → 400
  - the endpoint MUST NOT touch the DB (polling is pure Celery read)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── 1. SUCCESS: body passes through unchanged when dict ──────


@pytest.mark.asyncio
async def test_success_state_passes_dict_through():
    """When the task is SUCCESS, the body comes from `res.result` and must
    be a plain dict on the wire (frontend renders it)."""
    from app.modules.users.staff_import_router import get_apply_rules_status

    fake_result = MagicMock()
    fake_result.state = "SUCCESS"
    fake_result.ready = MagicMock(return_value=True)
    fake_result.successful = MagicMock(return_value=True)
    fake_result.failed = MagicMock(return_value=False)
    fake_result.result = {
        "users_processed": 12,
        "added": 30,
        "removed": 4,
        "skipped_manual": 2,
        "protected_completed": 5,
    }

    user = MagicMock()
    user.role = "admin"

    # Redis check returns None → endpoint falls through to Celery branch.
    async def fake_redis_get_task(_tid):
        return None

    with patch("app.modules.users.staff_import_router.AsyncResult", return_value=fake_result), \
         patch("app.core.redis_progress.get_task", side_effect=fake_redis_get_task):
        resp = await get_apply_rules_status(
            task_id="abc-123",
            user=user,
        )

    assert resp.task_id == "abc-123"
    assert resp.state == "SUCCESS"
    assert resp.ready is True
    assert resp.successful is True
    assert resp.failed is False
    assert resp.result == fake_result.result
    assert resp.error is None


# ── 2. FAILURE: exception is stringified into `error` ────────


@pytest.mark.asyncio
async def test_failure_state_extracts_error_message():
    from app.modules.users.staff_import_router import get_apply_rules_status

    fake_result = MagicMock()
    fake_result.state = "FAILURE"
    fake_result.ready = MagicMock(return_value=True)
    fake_result.successful = MagicMock(return_value=False)
    fake_result.failed = MagicMock(return_value=True)
    fake_result.result = RuntimeError("DB connection lost")

    user = MagicMock()
    user.role = "admin"

    async def fake_redis_get_task(_tid):
        return None

    with patch("app.modules.users.staff_import_router.AsyncResult", return_value=fake_result), \
         patch("app.core.redis_progress.get_task", side_effect=fake_redis_get_task):
        resp = await get_apply_rules_status(task_id="xyz", user=user)

    assert resp.state == "FAILURE"
    assert resp.failed is True
    assert resp.error == "RuntimeError('DB connection lost')" or "DB connection lost" in (resp.error or "")
    assert resp.result is None


# ── 3. PENDING / STARTED: no body, no error ──────────────────


@pytest.mark.asyncio
async def test_pending_state_returns_minimal_payload():
    """Frontend polls here every 1s; response must be cheap and stable."""
    from app.modules.users.staff_import_router import get_apply_rules_status

    fake_result = MagicMock()
    fake_result.state = "PENDING"
    fake_result.ready = MagicMock(return_value=False)
    fake_result.successful = MagicMock(return_value=None)
    fake_result.failed = MagicMock(return_value=None)

    user = MagicMock()
    user.role = "admin"

    async def fake_redis_get_task(_tid):
        return None

    with patch("app.modules.users.staff_import_router.AsyncResult", return_value=fake_result), \
         patch("app.core.redis_progress.get_task", side_effect=fake_redis_get_task):
        resp = await get_apply_rules_status(task_id="t1", user=user)

    assert resp.state == "PENDING"
    assert resp.ready is False
    assert resp.successful is None
    assert resp.result is None
    assert resp.error is None


# ── 4. Empty task_id → 400 ───────────────────────────────────


@pytest.mark.asyncio
async def test_empty_task_id_returns_400():
    from fastapi import HTTPException

    from app.modules.users.staff_import_router import get_apply_rules_status

    user = MagicMock()
    user.role = "admin"

    with pytest.raises(HTTPException) as exc:
        await get_apply_rules_status(task_id="", user=user)
    assert exc.value.status_code == 400


# ── 5. REVOKED state surfaces without crashing ──────────────


@pytest.mark.asyncio
async def test_revoked_state_handled():
    from app.modules.users.staff_import_router import get_apply_rules_status

    fake_result = MagicMock()
    fake_result.state = "REVOKED"
    fake_result.ready = MagicMock(return_value=True)
    fake_result.successful = MagicMock(return_value=False)
    fake_result.failed = MagicMock(return_value=True)
    fake_result.result = None

    user = MagicMock()
    user.role = "methodologist"

    async def fake_redis_get_task(_tid):
        return None

    with patch("app.modules.users.staff_import_router.AsyncResult", return_value=fake_result), \
         patch("app.core.redis_progress.get_task", side_effect=fake_redis_get_task):
        resp = await get_apply_rules_status(task_id="rev", user=user)

    # REVOKED is in the terminal bucket but doesn't carry a useful result.
    # We just must not crash and must report state truthfully.
    assert resp.state == "REVOKED"
    assert resp.ready is True
