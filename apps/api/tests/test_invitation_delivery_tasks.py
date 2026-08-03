from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.celery_app import celery_app
from app.modules.admin.superadmin.operations import REQUIRED_CELERY_TASKS
from app.modules.users.invitations_service import (
    TransientInvitationDeliveryError,
    is_transient_delivery_category,
)
from app.modules.users.tasks import _deliver_invitation, deliver_invitation_task


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _query_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_task_binds_lookup_to_tenant_and_invitation_id():
    tenant_id, invitation_id = uuid4(), uuid4()
    invitation = SimpleNamespace(
        id=invitation_id,
        tenant_id=tenant_id,
        status="pending",
        delivery_status="pending",
        delivery_failure_category=None,
        token="opaque-token",
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[None, _query_result(invitation)])

    with (
        patch("app.modules.users.tasks.async_session_factory", return_value=_SessionContext(db)),
        patch(
            "app.modules.users.tasks.attempt_invitation_delivery",
            new=AsyncMock(
                return_value={"delivery_status": "sent", "delivery_attempt_count": 1}
            ),
        ) as deliver,
    ):
        result = await _deliver_invitation(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
        )

    assert result["status"] == "sent"
    deliver.assert_awaited_once()
    assert deliver.await_args.kwargs["tenant_id"] == tenant_id
    assert deliver.await_args.kwargs["invitation_id"] == invitation_id
    assert deliver.await_args.kwargs["invite_url"].endswith("opaque-token")


@pytest.mark.asyncio
async def test_task_does_not_disclose_or_deliver_cross_tenant_invitation():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[None, _query_result(None)])

    with (
        patch("app.modules.users.tasks.async_session_factory", return_value=_SessionContext(db)),
        patch("app.modules.users.tasks.attempt_invitation_delivery", new=AsyncMock()) as deliver,
    ):
        result = await _deliver_invitation(
            tenant_id=uuid4(),
            invitation_id=uuid4(),
        )

    assert result == {"status": "not_found"}
    deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_is_idempotent_after_successful_delivery():
    invitation = SimpleNamespace(
        status="pending",
        delivery_status="sent",
        delivery_failure_category=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[None, _query_result(invitation)])

    with (
        patch("app.modules.users.tasks.async_session_factory", return_value=_SessionContext(db)),
        patch("app.modules.users.tasks.attempt_invitation_delivery", new=AsyncMock()) as deliver,
    ):
        result = await _deliver_invitation(tenant_id=uuid4(), invitation_id=uuid4())

    assert result == {"status": "skipped", "reason": "already_sent"}
    deliver.assert_not_awaited()


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("provider_timeout", True),
        ("provider_unreachable", True),
        ("provider_rate_limited", True),
        ("provider_unavailable", True),
        ("provider_rejected", False),
        ("provider_unconfigured", False),
    ],
)
def test_retry_classification_is_bounded_to_transient_provider_failures(category, expected):
    assert is_transient_delivery_category(category) is expected


def test_invitation_task_is_registered_and_operationally_required():
    assert deliver_invitation_task.name == "users.deliver_invitation"
    assert "users.deliver_invitation" in celery_app.tasks
    assert "users.deliver_invitation" in REQUIRED_CELERY_TASKS
    assert deliver_invitation_task.max_retries == 3
    assert deliver_invitation_task.retry_backoff == 5
    assert deliver_invitation_task.retry_backoff_max == 60


def test_transient_marker_contains_no_delivery_payload():
    error = TransientInvitationDeliveryError("provider_timeout")
    assert str(error) == "provider_timeout"
    assert "http" not in str(error).lower()
