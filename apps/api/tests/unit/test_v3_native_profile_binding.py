"""Native V3 profile binding under the owned delivery and source lock."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.native_profile_binding import KEY, POLICY_ID, bind_native_profile
from app.modules.ai.v3.provider_profile import V3ProfiledClient
from app.modules.ai.v3.revision_policy import KEY as REVISION_KEY
from app.modules.ai.v3.revision_policy import LEGACY_POLICY, POLICY
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal


class Session:
    def __init__(self, job):
        self.job = job
        self.commits = 0
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    async def scalar(self, query):
        return self.job
    async def commit(self):
        self.commits += 1


@pytest.fixture
def owned(monkeypatch):
    tenant, user, job_id = uuid4(), uuid4(), str(uuid4())
    job = SimpleNamespace(user_id=user, status="running", result={"unrelated": "keep"},
                          params={"source_analysis": {"generation_engine": "v3_cogen", REVISION_KEY: POLICY}})
    session = Session(job)
    journal = WorkerCycleJournal(str(tenant), job_id, lambda: session)
    journal.expected_revision_policy = POLICY
    journal.expected_revision_actor = user
    journal.expected_revision_source = SimpleNamespace(verify_locked=AsyncMock(return_value=True))
    journal.expected_revision_plan = {"source": "exact"}
    journal.repository._set_tenant = AsyncMock()
    lock = AsyncMock()
    monkeypatch.setattr("app.modules.ai.delivery_ownership.lock_owned_delivery", lock)
    token = delivery_id.set(str(uuid4()))
    client = object.__new__(V3ProfiledClient)
    client._fingerprint = "a" * 64
    yield journal, session, job, user, client, lock
    delivery_id.reset(token)


@pytest.mark.asyncio
async def test_new_binding_and_same_profile_are_owner_source_checked_and_idempotent(owned):
    journal, session, job, user, client, lock = owned
    await bind_native_profile(journal=journal, user_id=user, client=client)
    expected = {"policy": POLICY_ID, "fingerprint": "a" * 64}
    assert job.result == {"unrelated": "keep", KEY: expected} and journal.expected_native_profile == expected
    await bind_native_profile(journal=journal, user_id=user, client=client)
    assert job.result == {"unrelated": "keep", KEY: expected}
    assert lock.await_count == 2 and journal.expected_revision_source.verify_locked.await_count == 2
    assert session.commits == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["foreign_actor", "stale_source", "legacy_policy", "invalid_revision", "status", "delivery"])
async def test_wrong_owner_or_stale_source_holds_before_write(owned, reason):
    journal, session, job, user, client, lock = owned
    if reason == "foreign_actor":
        user = uuid4()
    elif reason == "stale_source":
        journal.expected_revision_source.verify_locked.return_value = False
    elif reason == "legacy_policy":
        job.params["source_analysis"][REVISION_KEY] = LEGACY_POLICY
    elif reason == "invalid_revision":
        job.params["source_analysis"][REVISION_KEY] = "unknown"
    elif reason == "status":
        job.status = "failed"
    else:
        lock.side_effect = DeliveryOwnershipLostError("lost")
    before = deepcopy(job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_native_profile(journal=journal, user_id=user, client=client)
    assert job.result == before and session.commits == 0 and journal.expected_native_profile is None


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", [None, {}, {"policy": POLICY_ID, "fingerprint": "b" * 64},
                                     {"policy": "other", "fingerprint": "a" * 64},
                                     {"policy": POLICY_ID, "fingerprint": "a" * 64, "extra": True}, "invalid"])
async def test_existing_invalid_or_foreign_profile_marker_holds_without_write(owned, marker):
    journal, session, job, user, client, _ = owned
    job.result[KEY] = marker
    before = deepcopy(job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_native_profile(journal=journal, user_id=user, client=client)
    assert job.result == before and session.commits == 0 and journal.expected_native_profile is None


@pytest.mark.asyncio
async def test_later_profile_drift_is_held_at_delivery_lock_before_inference(owned):
    journal, session, job, user, client, _ = owned
    await bind_native_profile(journal=journal, user_id=user, client=client)
    job.result[KEY] = {"policy": POLICY_ID, "fingerprint": "b" * 64}
    inference = AsyncMock()
    with pytest.raises(DeliveryOwnershipLostError, match="generation_native_profile_changed"):
        await journal._lock_delivery(session)
        await inference()
    inference.assert_not_awaited()
    assert session.commits == 1


@pytest.mark.asyncio
async def test_wrong_profile_type_and_legacy_journal_rejected_without_writes(owned):
    journal, session, job, user, client, _ = owned
    before = deepcopy(job.result)
    with pytest.raises(ValueError, match="v3_native_profile_scope_invalid"):
        await bind_native_profile(journal=journal, user_id=user, client=object())
    journal.expected_revision_policy = LEGACY_POLICY
    with pytest.raises(ValueError, match="v3_native_profile_scope_invalid"):
        await bind_native_profile(journal=journal, user_id=user, client=client)
    assert job.result == before and session.commits == 0
