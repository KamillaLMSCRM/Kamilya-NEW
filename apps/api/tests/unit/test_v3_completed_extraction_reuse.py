import asyncio
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.modules.ai import job_service
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3 import completed_extraction_reuse as reuse
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError, _digest
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.qa_luna_pending_policy import KEY, MANAGED_POLICY
from app.modules.ai.v3.revision_policy import KEY as REVISION_KEY
from app.modules.ai.v3.revision_policy import POLICY as REVISION_POLICY
from app.modules.ai.v3.stage_checkpoint import _digest as stage_digest


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


@pytest.fixture
def owned(monkeypatch):
    actor, parent_id, child_id, document = uuid4(), str(uuid4()), str(uuid4()), str(uuid4())
    identity = {
        "tenant_id": str(QA_TENANT),
        "job_id": child_id,
        "document_id": document,
        "source_revision": "document:" + "a" * 64,
        "source_sha256": "b" * 64,
        "unit_sha256": "c" * 64,
        "context_sha256": "d" * 64,
        "prompt_sha256": "e" * 64,
        "route_fingerprint": "f" * 64,
        "unit_start": "0",
        "unit_end": "10",
    }
    plan = {"schema": "v3-rule-extraction-checkpoint-v1", "identity": identity}
    parent_plan = {"schema": plan["schema"], "identity": {**identity, "job_id": parent_id}}
    params = {
        "documents": [document],
        "reference_decisions": [{"synthetic": True}],
        "source_analysis": {"generation_engine": "evidence_v3", KEY: MANAGED_POLICY, REVISION_KEY: REVISION_POLICY},
    }
    route = {"policy": "v3-owned-route-binding-v1", "fingerprint": "f" * 64}
    marker = {
        "policy": "v3-pending-stages-v1",
        "entries": {"a" * 64: {"claim_key": "lesson-claim", "result_key": "lesson-result", "token": "b" * 32}},
    }
    now = datetime.now(UTC)
    parent = SimpleNamespace(
        id=parent_id,
        tenant_id=QA_TENANT,
        user_id=actor,
        status="failed",
        course_id=None,
        created_at=now - timedelta(days=1),
        params=deepcopy(params),
        result={"v3_owned_route_binding": deepcopy(route), "v3_pending_stages": marker},
    )
    parent.params["generation_abandonment"] = {
        "policy": "unknown-provider-abandon-v1",
        "actor_id": str(actor),
        "acknowledged": True,
        "provider_outcome": "unknown",
        "cost": "unknown",
        "pending_marker_sha256": job_service._abandon_marker_digest(parent),
    }
    child = SimpleNamespace(
        id=child_id,
        tenant_id=QA_TENANT,
        user_id=actor,
        status="running",
        course_id=None,
        created_at=now,
        params={**deepcopy(params), reuse.PARENT_KEY: parent_id},
        result={"v3_owned_route_binding": deepcopy(route)},
    )
    response = {"rules": [{"rule_id": "r1", "statement": "synthetic", "source_quote": ""}]}
    metadata = {
        "model": "gpt-5.6-luna",
        "usage": {"input_tokens": 7, "output_tokens": 3, "cached_input_tokens": None, "reasoning_tokens": None},
    }
    saved = {
        "identity": _digest(parent_plan),
        "response": response,
        "response_sha256": _digest(response),
        "direct_metadata": metadata,
        "direct_metadata_sha256": stage_digest(metadata),
    }
    calls = []

    committer = AsyncMock()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def commit(self):
            await committer()

        async def scalar(self, query):
            calls.append(query)
            return parent

    journal = PendingStageJournal(str(QA_TENANT), actor, child_id, Session, verify_source=AsyncMock(return_value=True))
    monkeypatch.setattr(reuse, "_locked_job", AsyncMock(return_value=child))
    journal.repository = SimpleNamespace(load_plan=AsyncMock(side_effect=reuse.AIGenerationCheckpointError("generation_plan_not_found")))
    parent_rows = [SimpleNamespace(module_key="cycle", lesson_key="lesson", content_status="completed",
                                  review_status="completed", assessment_status="completed")]

    class ParentJournal:
        def __init__(self, tenant, job, _sessions):
            assert tenant == str(QA_TENANT) and job == parent_id
            self.repository = SimpleNamespace(load_checkpoints=AsyncMock(return_value=parent_rows))
        def _owned_key(self, key):
            return key

        async def read_owned_value_in_session(self, _session, key, expected):
            assert key == "v3-result:" + _digest(parent_plan) and expected == parent_plan
            return saved

    monkeypatch.setattr(reuse, "WorkerCycleJournal", ParentJournal)
    return SimpleNamespace(
        actor=actor,
        parent=parent,
        child=child,
        journal=journal,
        plan=plan,
        parent_id=parent_id,
        saved=saved,
        calls=calls,
        commits=committer,
        parent_rows=parent_rows,
    )


@pytest.mark.asyncio
async def test_completed_extraction_is_immutable_copy_and_does_not_mutate_parent(owned):
    before = deepcopy(owned.parent.__dict__)
    candidate = await reuse.lookup_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    assert candidate is not None and candidate.source_job_id == owned.parent_id
    assert candidate.original_metadata()["model"] == "gpt-5.6-luna"
    candidate.response()["rules"].clear()
    assert len(candidate.response()["rules"]) == 1 and owned.parent.__dict__ == before
    assert len(owned.calls) == 1 and owned.calls[0]._for_update_arg.read is True
    owned.journal.verify_source.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        "actor",
        "tenant",
        "child_tenant",
        "order",
        "status",
        "abandonment",
        "parent_policy",
        "child_policy",
        "revision",
        "documents",
        "reference",
        "route",
        "source",
        "response",
        "metadata",
        "model",
        "parent_id",
    ],
)
async def test_invalid_parent_or_checkpoint_fails_closed_before_reuse(owned, drift):
    if drift == "actor":
        owned.parent.user_id = uuid4()
    if drift == "tenant":
        owned.parent.tenant_id = uuid4()
    if drift == "child_tenant":
        owned.child.tenant_id = uuid4()
    if drift == "order":
        owned.parent.created_at = owned.child.created_at
    if drift == "status":
        owned.parent.status = "interrupted"
    if drift == "abandonment":
        owned.parent.params["generation_abandonment"]["acknowledged"] = False
    if drift == "parent_policy":
        owned.parent.params["source_analysis"][KEY] = "other"
    if drift == "child_policy":
        owned.child.params["source_analysis"][KEY] = "other"
    if drift == "revision":
        owned.parent.params["source_analysis"][REVISION_KEY] = "old"
    if drift == "documents":
        owned.parent.params["documents"] = [str(uuid4())]
    if drift == "reference":
        owned.parent.params["reference_decisions"] = []
    if drift == "route":
        owned.parent.result["v3_owned_route_binding"]["fingerprint"] = "a" * 64
    if drift == "source":
        owned.journal.verify_source.return_value = False
    if drift == "response":
        owned.saved["response"]["rules"][0]["statement"] = "changed"
    if drift == "metadata":
        owned.saved["direct_metadata"]["usage"]["input_tokens"] = 100
    if drift == "model":
        owned.saved["direct_metadata"]["model"] = "gpt-6-luna"
        owned.saved["direct_metadata_sha256"] = stage_digest(owned.saved["direct_metadata"])
    parent_id = owned.journal.job_id if drift == "parent_id" else owned.parent_id
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_extraction_reuse_unverified"):
        await reuse.lookup_completed_extraction(owned.journal, owned.plan, parent_id)


@pytest.mark.asyncio
async def test_requested_extraction_marked_pending_is_never_read(owned, monkeypatch):
    parent_plan = {"schema": owned.plan["schema"], "identity": {**owned.plan["identity"], "job_id": owned.parent_id}}
    entry = next(iter(owned.parent.result["v3_pending_stages"]["entries"].values()))
    entry["result_key"] = "v3-result:" + _digest(parent_plan)
    owned.parent.params["generation_abandonment"]["pending_marker_sha256"] = job_service._abandon_marker_digest(
        owned.parent
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("pending result must not be read")

    monkeypatch.setattr(reuse, "WorkerCycleJournal", forbidden)
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_extraction_reuse_unverified"):
        await reuse.lookup_completed_extraction(owned.journal, owned.plan, owned.parent_id)


@pytest.mark.asyncio
async def test_source_verifier_cancellation_is_not_converted(owned):
    owned.journal.verify_source.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await reuse.lookup_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    assert not owned.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", [{"policy": "v3-pending-stages-v1", "entries": {}}, None])
async def test_child_pending_presence_fences_preclaim_lookup(owned, pending):
    owned.child.result["v3_pending_stages"] = pending
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_extraction_reuse_unverified"):
        await reuse.lookup_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    owned.journal.verify_source.assert_not_awaited()
    assert not owned.calls


@pytest.mark.asyncio
async def test_reuse_records_only_origin_and_cold_revalidates_without_usage_copy(owned):
    parent_before = deepcopy(owned.parent.__dict__)
    response = await reuse.reuse_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    assert response == owned.saved["response"]
    first = deepcopy(owned.child.result)
    assert "direct_metadata" not in first
    proof = first[reuse.REUSE_KEY]["entries"][_digest(owned.plan)]
    assert proof == {"source_job_id": owned.parent_id,
                     "source_plan_sha256": owned.saved["identity"],
                     "response_sha256": owned.saved["response_sha256"],
                     "original_metadata_sha256": owned.saved["direct_metadata_sha256"]}
    assert await reuse.reuse_completed_extraction(owned.journal, owned.plan, owned.parent_id) == response
    assert owned.child.result == first
    assert owned.parent.__dict__ == parent_before
    assert owned.commits.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["content_status", "review_status", "assessment_status"])
async def test_reuse_rejects_partial_parent_checkpoint(owned, field):
    setattr(owned.parent_rows[0], field, "pending")
    with pytest.raises(ExtractionOutcomeUnknownError):
        await reuse.reuse_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    owned.commits.assert_not_awaited()
    assert reuse.REUSE_KEY not in owned.child.result


@pytest.mark.asyncio
async def test_reuse_rejects_existing_child_stage_without_replacing_it(owned):
    owned.journal.repository.load_plan.side_effect = None
    owned.journal.repository.load_plan.return_value = object()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await reuse.reuse_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    owned.commits.assert_not_awaited()


@pytest.mark.asyncio
async def test_reuse_rejects_changed_provenance_without_overwriting(owned):
    await reuse.reuse_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    entry = owned.child.result[reuse.REUSE_KEY]["entries"][_digest(owned.plan)]
    entry["response_sha256"] = "0" * 64
    before = deepcopy(owned.child.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await reuse.reuse_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    assert owned.child.result == before
    assert owned.commits.await_count == 1


@pytest.mark.asyncio
async def test_admission_requires_same_owned_abandoned_managed_parent(owned):
    session = SimpleNamespace(scalar=AsyncMock(return_value=owned.parent))
    params = dict(tenant_id=QA_TENANT, user_id=owned.actor, parent_job_id=UUID(owned.parent_id),
                  policy=MANAGED_POLICY, documents=owned.parent.params["documents"],
                  references=owned.parent.params["reference_decisions"], course_id=None)
    await reuse.validate_parent_admission(session, **params)
    for changed in ({"tenant_id": uuid4()}, {"policy": "qa-direct-luna-diversity-v3"},
                    {"user_id": uuid4()}, {"course_id": uuid4()}, {"documents": [str(uuid4())]},
                    {"references": []}):
        with pytest.raises(ValueError):
            await reuse.validate_parent_admission(session, **(params | changed))


@pytest.mark.asyncio
async def test_parent_bound_stage_does_not_bypass_origin_on_child_replay(monkeypatch):
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3 import direct_luna_owned_stage as stage
    from tests.unit.test_direct_luna_owned_stage import options, setup
    _, journal, _, _, validate = setup()
    journal.completed_extraction_parent_job_id = str(uuid4())
    plan = {"schema": "v3-rule-extraction-checkpoint-v1", "identity": {}}
    client = ManagedLunaClient(base_url="http://127.0.0.1:18999/v1", api_key="synthetic" * 6,
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision="synthetic")
    monkeypatch.setattr(stage, "inspect_owned_stage", AsyncMock(return_value=SimpleNamespace(
        decision="replay", result={"unverified_child": True})))
    restore = AsyncMock(side_effect=ExtractionOutcomeUnknownError("parent_revalidation_required"))
    monkeypatch.setattr(reuse, "reuse_completed_extraction", restore)
    client.prepare = AsyncMock(side_effect=AssertionError("provider forbidden"))
    client.invoke = AsyncMock(side_effect=AssertionError("provider forbidden"))
    with pytest.raises(ExtractionOutcomeUnknownError, match="parent_revalidation_required"):
        await stage.run_direct_owned_stage(**options(journal, client, plan, validate))
    restore.assert_awaited_once()
    client.prepare.assert_not_awaited()
    client.invoke.assert_not_awaited()


@pytest.mark.parametrize("value", [None, True, 1, "", "not-a-uuid", [], {}])
def test_persisted_malformed_parent_never_becomes_cache_miss(value):
    with pytest.raises(ExtractionOutcomeUnknownError):
        reuse.read_parent_marker({reuse.PARENT_KEY: value}, MANAGED_POLICY)


def test_parent_snapshot_distinguishes_absence_valid_uuid_and_route_drift():
    parent = str(uuid4())
    assert reuse.read_parent_marker({}, MANAGED_POLICY) is None
    assert reuse.read_parent_marker({reuse.PARENT_KEY: parent}, MANAGED_POLICY) == parent
    assert reuse.read_parent_marker({reuse.PARENT_KEY: str(uuid4())}, MANAGED_POLICY) != parent
    with pytest.raises(ExtractionOutcomeUnknownError):
        reuse.read_parent_marker({reuse.PARENT_KEY: parent}, "ordinary")


@pytest.mark.asyncio
async def test_boolean_numeric_reference_drift_is_not_equivalent(owned):
    owned.parent.params["reference_decisions"] = [{"confirmed": True}]
    owned.child.params["reference_decisions"] = [{"confirmed": 1}]
    with pytest.raises(ExtractionOutcomeUnknownError):
        await reuse.lookup_completed_extraction(owned.journal, owned.plan, owned.parent_id)
    owned.commits.assert_not_awaited()
    session = SimpleNamespace(scalar=AsyncMock(return_value=owned.parent))
    with pytest.raises(ValueError):
        await reuse.validate_parent_admission(session, tenant_id=QA_TENANT, user_id=owned.actor,
            parent_job_id=UUID(owned.parent_id), policy=MANAGED_POLICY,
            documents=owned.parent.params["documents"], references=[{"confirmed": 1}], course_id=None)
