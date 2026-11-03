"""Fresh review selection is server-owned; old job markers remain unchanged."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id
from app.modules.ai.v3.revision_policy import (
    LEGACY_REVIEW_POLICY,
    POLICY,
    REVIEW_KEY,
    REVIEW_POLICY,
    read_review_policy,
    stamp_policy,
)
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal


def test_fresh_admission_overwrites_untrusted_review_selection():
    value={REVIEW_KEY: 'untrusted', 'generation_engine': 'evidence_v3'}
    original=deepcopy(value)
    result=stamp_policy(value)
    assert result[REVIEW_KEY] == REVIEW_POLICY and value == original
    assert read_review_policy(result) == REVIEW_POLICY
    assert read_review_policy({'v3_revision_policy': POLICY}) is None
    assert read_review_policy({REVIEW_KEY: LEGACY_REVIEW_POLICY}) == LEGACY_REVIEW_POLICY
    assert REVIEW_POLICY != LEGACY_REVIEW_POLICY


@pytest.mark.parametrize('value',[None,True,{},'foreign'])
def test_present_invalid_review_marker_is_never_legacy(value):
    with pytest.raises(ValueError,match='review_policy_invalid'):
        read_review_policy({REVIEW_KEY:value})


@pytest.mark.asyncio
@pytest.mark.parametrize('expected,observed',[(None,REVIEW_POLICY),(REVIEW_POLICY,None),
    (LEGACY_REVIEW_POLICY,REVIEW_POLICY),(REVIEW_POLICY,LEGACY_REVIEW_POLICY)])
async def test_review_policy_changed_before_checkpoint_fails_without_write(monkeypatch,expected,observed):
    tenant,job=str(uuid4()),str(uuid4())
    analysis={} if observed is None else {REVIEW_KEY:observed}
    row=SimpleNamespace(params={'source_analysis':analysis})
    session=SimpleNamespace(scalar=AsyncMock(return_value=row))
    journal=WorkerCycleJournal(tenant,job,None)
    journal.repository._set_tenant=AsyncMock()
    journal.review_policy_bound=True
    journal.expected_review_policy=expected
    monkeypatch.setattr('app.modules.ai.delivery_ownership.lock_owned_delivery',AsyncMock())
    token=delivery_id.set(job)
    try:
        with pytest.raises(DeliveryOwnershipLostError,match='generation_review_policy_changed'):
            await journal._lock_delivery(session)
    finally:
        delivery_id.reset(token)
    assert session.scalar.await_count == 1
