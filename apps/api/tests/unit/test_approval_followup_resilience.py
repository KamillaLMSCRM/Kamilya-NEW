"""Executable resilience checks for approval delivery claims."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.course_approval.notification_tasks import _claim_delivery


class _FakeDb:
    def __init__(self, delivery):
        self.delivery = delivery
        self.commits = 0

    async def scalar(self, _query):
        return self.delivery

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_claim_persists_a_bounded_recovery_lease():
    delivery = SimpleNamespace(status="queued", attempt_count=0, error_category=None, claim_token=None, next_attempt_at=None)
    db = _FakeDb(delivery)
    claimed = await _claim_delivery(db, tenant_id=SimpleNamespace(), delivery_id=SimpleNamespace())
    assert claimed is delivery
    assert delivery.status == "accepted"
    assert delivery.attempt_count == 1
    assert delivery.claim_token is not None
    assert delivery.next_attempt_at > datetime.now(UTC)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_exhausted_stale_claim_is_terminal_not_permanently_accepted():
    delivery = SimpleNamespace(status="accepted", attempt_count=8, error_category=None, claim_token=object(), next_attempt_at=datetime.now(UTC))
    db = _FakeDb(delivery)
    claimed = await _claim_delivery(db, tenant_id=SimpleNamespace(), delivery_id=SimpleNamespace())
    assert claimed is None
    assert delivery.status == "terminal"
    assert delivery.error_category == "claim_lease_exhausted"
    assert delivery.claim_token is None
    assert delivery.next_attempt_at is None
    assert db.commits == 1
