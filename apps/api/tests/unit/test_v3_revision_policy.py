"""Fresh revision marker is server-owned and loaded under delivery ownership."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.v3.revision_policy import KEY, POLICY, policy_matches, read_policy, stamp_policy


@pytest.mark.parametrize("value", [None, False, 1, "unknown", {}, []])
def test_present_invalid_marker_fails_closed(value):
    with pytest.raises(ValueError, match="v3_revision_policy_invalid"):
        read_policy({KEY: value})


def test_missing_is_legacy_and_exact_marker_is_fresh():
    assert read_policy({}) is None
    assert read_policy({KEY: POLICY}) == POLICY
    assert policy_matches({KEY: POLICY}, POLICY)
    assert not policy_matches({}, POLICY)
    assert not policy_matches({KEY: None}, None)
    assert not policy_matches({KEY: POLICY}, None)


def test_admission_stamp_overrides_untrusted_marker_without_mutating_input():
    from app.modules.ai.v3.revision_policy import REVIEW_KEY, REVIEW_POLICY
    supplied = {KEY: "spoofed", "generation_engine": "evidence_v3"}
    assert stamp_policy(supplied) == {KEY: POLICY, REVIEW_KEY: REVIEW_POLICY, "generation_engine": "evidence_v3"}
    assert supplied[KEY] == "spoofed"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fresh", "legacy", "actor", "documents", "invalid"])
async def test_owned_loader_uses_persisted_job(monkeypatch, mode):
    from app.modules.ai import job_service, pipeline
    from app.modules.ai.direct_source import DirectSourceError

    tenant, actor = uuid4(), uuid4()
    document = str(uuid4())
    analysis = {} if mode == "legacy" else {KEY: None if mode == "invalid" else POLICY}
    job = SimpleNamespace(user_id=uuid4() if mode == "actor" else actor, status="running",
                          params={"documents": [str(uuid4()) if mode == "documents" else document],
                                  "source_analysis": analysis})
    class Session:
        execute = AsyncMock()
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: Session())
    lock = AsyncMock()
    monkeypatch.setattr(pipeline, "lock_owned_delivery", lock)
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    if mode in {"actor", "documents", "invalid"}:
        with pytest.raises((ValueError, DirectSourceError, pipeline.GenerationJobOwnerMismatchError)):
            await pipeline._load_owned_revision_policy("job", tenant, actor, [document])
    else:
        assert await pipeline._load_owned_revision_policy("job", tenant, actor, [document]) == (None if mode == "legacy" else POLICY)
    lock.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fresh", "removed", "invalid", "actor"])
async def test_ordinary_journal_checks_owned_policy_under_lock(monkeypatch, mode):
    from app.modules.ai import delivery_ownership
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    actor = uuid4()
    analysis = {} if mode == "removed" else {KEY: None if mode == "invalid" else POLICY}
    job = SimpleNamespace(user_id=uuid4() if mode == "actor" else actor,
                          params={"source_analysis": analysis})
    session = SimpleNamespace(scalar=AsyncMock(return_value=job))
    journal = WorkerCycleJournal(str(uuid4()), "job", lambda: None)
    journal.expected_revision_policy = POLICY
    journal.expected_revision_actor = actor
    journal.expected_revision_source = SimpleNamespace(verify_locked=AsyncMock(return_value=True))
    journal.expected_revision_plan = {"schema": "v3-stage-checkpoint-v1"}
    journal.repository._set_tenant = AsyncMock()
    monkeypatch.setattr(delivery_ownership, "lock_owned_delivery", AsyncMock())
    token = delivery_ownership.delivery_id.set("delivery")
    try:
        if mode == "fresh":
            await journal._lock_delivery(session)
        else:
            with pytest.raises(delivery_ownership.DeliveryOwnershipLostError):
                await journal._lock_delivery(session)
    finally:
        delivery_ownership.delivery_id.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift_at", ["claim", "finalize"])
async def test_pending_transaction_holds_on_revision_policy_drift(drift_at):
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.pending_stage_transactions import claim_with_pending, finalize_pending, has_pending
    from app.modules.ai.v3.stage_checkpoint import _digest
    from tests.unit.test_pending_stage_transactions import TxJournal, args

    journal = TxJournal()
    journal.job.params["source_analysis"][KEY] = POLICY
    arguments = args(journal)
    async def verifier(_session, job, _plan):
        return policy_matches(job.params["source_analysis"], POLICY)
    arguments["verify_source"] = verifier
    if drift_at == "claim":
        journal.job.params["source_analysis"][KEY] = "changed"
        with pytest.raises(ExtractionOutcomeUnknownError):
            await claim_with_pending(**arguments)
        assert not has_pending(journal.job.result)
    else:
        await claim_with_pending(**arguments)
        journal.job.params["source_analysis"][KEY] = "changed"
        with pytest.raises(ExtractionOutcomeUnknownError):
            await finalize_pending(**arguments, value={"identity": _digest(arguments["plan"]), "response": {"ok": True}})
        assert has_pending(journal.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "selection", "revision", "hash", "missing_context"])
async def test_ordinary_owned_source_rechecked_before_journal_access(monkeypatch, change):
    from dataclasses import replace

    from app.modules.ai import delivery_ownership
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal
    from tests.unit.test_owned_source_verifier import setup

    tenant, actor, corpus, job, row, plan, _ = setup()
    job.params["source_analysis"][KEY] = POLICY
    if change == "selection":
        job.params["documents"] = [str(uuid4())]
    if change == "revision":
        corpus = replace(corpus, documents=(replace(corpus.documents[0], source_revision="document:" + "b" * 64),))
    if change == "hash":
        row.content_sha256 = "c" * 64
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[job, row]))
    journal = WorkerCycleJournal(str(tenant), "job", lambda: None)
    journal.expected_revision_policy, journal.expected_revision_actor = POLICY, actor
    journal.expected_revision_plan = plan
    if change != "missing_context":
        journal.expected_revision_source = OwnedSourceContext(corpus, journal, tenant, actor, "job", tuple(corpus.document_ids))
    journal.repository._set_tenant = AsyncMock()
    monkeypatch.setattr(delivery_ownership, "lock_owned_delivery", AsyncMock())
    token = delivery_ownership.delivery_id.set("delivery")
    try:
        if change == "none":
            await journal._lock_delivery(session)
        else:
            with pytest.raises(delivery_ownership.DeliveryOwnershipLostError):
                await journal._lock_delivery(session)
    finally:
        delivery_ownership.delivery_id.reset(token)
