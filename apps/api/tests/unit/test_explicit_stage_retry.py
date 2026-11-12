"""Owned explicit retry authorizations must never erase unknown-call custody."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ai import job_service
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3 import explicit_stage_retry as retry
from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
from app.modules.ai.v3.qa_luna_pending_policy import KEY as ROUTE_KEY
from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.stage_checkpoint import _digest
from app.modules.source_editorial_review.service import SOURCE_PINS
from tests.unit.test_ai_job_admission import _CommitSession
from tests.unit.test_owned_stage_inspection import setup_journal


@pytest.mark.parametrize(
    "override",
    [
        {"acknowledge_unknown_outcome": False},
        {"acknowledge_unknown_outcome": "true"},
        {"acknowledge_unknown_outcome": 1},
        {"stage_sha256": "bad"},
        {"stage_sha256": "A" * 64},
        {"recovery_id": "bad"},
    ],
)
def test_retry_request_rejects_unacknowledged_or_invalid_identity(override):
    value = {"stage_sha256": "a" * 64, "recovery_id": str(uuid4()), "acknowledge_unknown_outcome": True}
    value.update(override)
    with pytest.raises(ValidationError):
        retry.UnknownStageRetryRequest(**value)


def test_retry_request_requires_explicit_acknowledgment():
    with pytest.raises(ValidationError):
        retry.UnknownStageRetryRequest(stage_sha256="a" * 64, recovery_id=uuid4())


def test_retry_request_rejects_client_supplied_recovery_overrides():
    with pytest.raises(ValidationError):
        retry.UnknownStageRetryRequest(
            stage_sha256="a" * 64,
            recovery_id=uuid4(),
            acknowledge_unknown_outcome=True,
            explicit_recovery={"policy": "client-controlled"},
        )


def test_retry_plan_without_ledger_preserves_original_exactly():
    plan = {
        "schema": "v3-stage-checkpoint-v1",
        "tenant_id": str(QA_TENANT),
        "job_id": str(uuid4()),
        "stage": "review",
        "group_id": "practical:simple:plan:v9:" + "c" * 64 + ":output=32768",
        "source_sha256": "a" * 64,
        "route_fingerprint": "b" * 64,
        "request_sha256": "d" * 64,
    }
    original = copy.deepcopy(plan)
    assert retry.retry_plan(plan, None) == original and plan == original


@pytest.fixture
def owned_case(monkeypatch):
    fake = setup_journal()
    actor, job_id = uuid4(), uuid4()
    fake.tenant_id, fake.job_id = str(QA_TENANT), str(job_id)
    fake.job.user_id, fake.job.tenant_id, fake.job.id = actor, QA_TENANT, job_id
    fake.job.status, fake.job.course_id, fake.job.errors = "interrupted", None, ["synthetic prior error"]
    document = str(uuid4())
    pins = {"synthetic": "owned-source-pins"}
    fake.job.params = {
        "documents": [document],
        "source_analysis": {
            "analysis_mode": "direct_source",
            "generation_engine": "evidence_v3",
            "v3_review_policy": SIMPLE_COURSE_REVIEW_V9_POLICY,
            ROUTE_KEY: MANAGED_POLICY,
            SOURCE_PINS: pins,
        },
    }
    plan = {
        "schema": "v3-stage-checkpoint-v1",
        "tenant_id": str(QA_TENANT),
        "job_id": str(job_id),
        "stage": "lesson",
        "group_id": "practical:simple:author-unit:v9:"
        + "c" * 64
        + ":plan="
        + "e" * 64
        + ":unit="
        + "f" * 64
        + ":output=32768",
        "source_sha256": "a" * 64,
        "route_fingerprint": "b" * 64,
        "request_sha256": "d" * 64,
    }
    digest, token = _digest(plan), "9" * 32
    claim, result = "v3-stage-claim:" + digest, "v3-stage-result:" + digest
    fake.plans.update({claim: copy.deepcopy(plan), result: copy.deepcopy(plan)})
    fake.values[claim] = {"identity": digest, "claim_token": token}
    fake.job.result = {
        PENDING_KEY: {
            "policy": "v3-pending-stages-v1",
            "entries": {digest: {"claim_key": claim, "result_key": result, "token": token}},
        },
        "v3_owned_route_binding": {"policy": "v3-owned-route-binding-v1", "fingerprint": "b" * 64},
        "other": {"must": "survive"},
    }
    settings = SimpleNamespace(
        DEPLOYMENT_ENVIRONMENT="render-development",
        AI_MANAGED_LUNA_QA_DEV_ENABLED=True,
        AI_DIRECT_LUNA_QA_DEV_ENABLED=False,
        AI_QA_LUNA_DEV_ENABLED=True,
    )
    monkeypatch.setattr(retry, "PendingStageJournal", lambda *_: fake)
    resolve_pins = AsyncMock(return_value={"synthetic": "approved"})
    monkeypatch.setattr("app.modules.source_editorial_review.service.resolve_pins", resolve_pins)
    inventory = AsyncMock(return_value={})
    monkeypatch.setattr(retry, "completed_inventory", inventory)
    return SimpleNamespace(
        fake=fake,
        job=fake.job,
        actor=actor,
        settings=settings,
        plan=plan,
        digest=digest,
        claim=claim,
        result=result,
        document=document,
        pins=pins,
        resolve_pins=resolve_pins,
        inventory=inventory,
    )


@pytest.mark.asyncio
async def test_authorization_preserves_unknown_call_and_cached_stages(owned_case):
    c = owned_case
    cached = [{"schema": "v3-stage-checkpoint-v1", "stage": f"cached-{i}"} for i in range(13)]
    for i, prior in enumerate(cached):
        c.fake.plans[f"cached-{i}"] = copy.deepcopy(prior)
        c.fake.values[f"cached-{i}"] = {"response": {"cached": i}}
    before_plans, before_values = copy.deepcopy(c.fake.plans), copy.deepcopy(c.fake.values)
    previous_result = copy.deepcopy(c.job.result)
    request = retry.UnknownStageRetryRequest(
        stage_sha256=c.digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True
    )
    candidate = await retry.retry_candidate(None, c.job, c.actor, c.settings)
    assert candidate["stage"] == c.digest and candidate["original_plan"] == c.plan
    archived = await retry.authorize_retry(None, c.job, c.actor, c.settings, request)
    c.resolve_pins.assert_awaited_once_with(None, QA_TENANT, (c.document,), c.pins)
    c.inventory.assert_awaited_once_with(None, c.job, c.actor)
    ledger = retry.checked_ledger(c.job.params)
    assert ledger["entries"][c.digest] == archived
    assert archived["original_plan"] == c.plan and archived["pending_sha256"] == _digest(previous_result[PENDING_KEY])
    assert archived["completed_stages"] == {}
    assert archived["previous_status"] == "interrupted" and archived["previous_errors"] == ["synthetic prior error"]
    assert (archived["prior_outcome"], archived["prior_usage"], archived["prior_cost"]) == ("UNKNOWN",) * 3
    assert c.job.result == {k: v for k, v in previous_result.items() if k != PENDING_KEY}
    assert c.fake.plans == before_plans and c.fake.values == before_values
    recovered = retry.retry_plan(c.plan, ledger)
    assert recovered == {
        **c.plan,
        "explicit_recovery": {
            "policy": retry.POLICY,
            "original_stage_sha256": c.digest,
            "recovery_id": str(request.recovery_id),
        },
    }
    assert c.plan == candidate["original_plan"]
    for prior in cached:
        assert retry.retry_plan(prior, ledger) == prior
    preserved = (copy.deepcopy(c.job.params), copy.deepcopy(c.job.result))
    with pytest.raises(ValueError):
        await retry.authorize_retry(None, c.job, c.actor, c.settings, request)
    assert (c.job.params, c.job.result) == preserved


@pytest.mark.asyncio
async def test_changed_source_approval_never_mutates_job_or_checkpoints(owned_case):
    c = owned_case
    c.resolve_pins.side_effect = ValueError("source approval changed")
    request = retry.UnknownStageRetryRequest(
        stage_sha256=c.digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True
    )
    before = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    with pytest.raises(ValueError, match="explicit_stage_retry_source_unverified"):
        await retry.authorize_retry(None, c.job, c.actor, c.settings, request)
    c.resolve_pins.assert_awaited_once_with(None, QA_TENANT, (c.document,), c.pins)
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == before


@pytest.mark.asyncio
async def test_completed_inventory_failure_never_mutates_job_or_checkpoints(owned_case):
    c = owned_case
    c.inventory.side_effect = RuntimeError("synthetic inventory unavailable")
    request = retry.UnknownStageRetryRequest(
        stage_sha256=c.digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True
    )
    before = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    with pytest.raises(RuntimeError, match="synthetic inventory unavailable"):
        await retry.authorize_retry(None, c.job, c.actor, c.settings, request)
    c.inventory.assert_awaited_once_with(None, c.job, c.actor)
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_documents", "empty_documents", "duplicate_documents", "missing_pins"])
async def test_missing_source_binding_rejected_before_mutation(owned_case, fault):
    c = owned_case
    if fault == "missing_documents":
        del c.job.params["documents"]
    elif fault == "empty_documents":
        c.job.params["documents"] = []
    elif fault == "duplicate_documents":
        c.job.params["documents"] *= 2
    else:
        del c.job.params["source_analysis"][SOURCE_PINS]
    request = retry.UnknownStageRetryRequest(
        stage_sha256=c.digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True
    )
    before = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    with pytest.raises(ValueError, match="explicit_stage_retry_source_unverified"):
        await retry.authorize_retry(None, c.job, c.actor, c.settings, request)
    c.resolve_pins.assert_not_awaited()
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse_id", [True, False])
async def test_second_operation_rejected_for_distinct_unknown_stage(owned_case, reuse_id):
    c = owned_case
    request = retry.UnknownStageRetryRequest(
        stage_sha256=c.digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True
    )
    await retry.authorize_retry(None, c.job, c.actor, c.settings, request)
    second = {**c.plan, "request_sha256": "7" * 64}
    digest, token = _digest(second), "8" * 32
    claim, result = "v3-stage-claim:" + digest, "v3-stage-result:" + digest
    c.fake.plans.update({claim: second, result: copy.deepcopy(second)})
    c.fake.values[claim] = {"identity": digest, "claim_token": token}
    c.job.result[PENDING_KEY] = {
        "policy": "v3-pending-stages-v1",
        "entries": {digest: {"claim_key": claim, "result_key": result, "token": token}},
    }
    other_request = retry.UnknownStageRetryRequest(
        stage_sha256=digest, recovery_id=request.recovery_id if reuse_id else uuid4(), acknowledge_unknown_outcome=True
    )
    before = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    assert await retry.retry_candidate(None, c.job, c.actor, c.settings) is None
    with pytest.raises(ValueError):
        await retry.authorize_retry(None, c.job, c.actor, c.settings, other_request)
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "wrong_actor",
        "wrong_tenant",
        "running",
        "failed",
        "course",
        "environment",
        "managed_disabled",
        "direct_enabled",
        "foreign_engine",
        "foreign_policy",
        "foreign_route",
        "source_first",
        "source_first_partitioned",
        "wrong_stage",
        "claim_marker",
        "result_present",
        "plan_source",
        "plan_route",
        "plan_owner",
        "plan_request",
        "recovered_stage",
        "two_pending",
        "bad_ledger",
    ],
)
async def test_rejected_retry_never_mutates_job_or_private_checkpoints(owned_case, fault):
    c, actor = owned_case, owned_case.actor
    if fault == "wrong_actor":
        actor = uuid4()
    elif fault == "wrong_tenant":
        c.job.tenant_id = uuid4()
    elif fault == "running":
        c.job.status = "running"
    elif fault == "failed":
        c.job.status = "failed"
    elif fault == "course":
        c.job.course_id = uuid4()
    elif fault == "environment":
        c.settings.DEPLOYMENT_ENVIRONMENT = "production"
    elif fault == "managed_disabled":
        c.settings.AI_MANAGED_LUNA_QA_DEV_ENABLED = False
    elif fault == "direct_enabled":
        c.settings.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    elif fault == "foreign_engine":
        c.job.params["source_analysis"]["generation_engine"] = "source_first_qa_v1"
    elif fault == "foreign_policy":
        c.job.params["source_analysis"]["v3_review_policy"] = "other"
    elif fault == "foreign_route":
        c.job.params["source_analysis"][ROUTE_KEY] = "other"
    elif fault == "source_first":
        c.job.result["source_first_commit_intent"] = None
    elif fault == "source_first_partitioned":
        c.job.result["source_first_partitioned_commit_intent"] = None
    elif fault == "claim_marker":
        c.fake.values[c.claim]["claim_token"] = "8" * 32
    elif fault == "result_present":
        c.fake.values[c.result] = {"existing": True}
    elif fault == "plan_source":
        c.fake.plans[c.claim]["source_sha256"] = "0" * 64
    elif fault == "plan_route":
        c.job.result["v3_owned_route_binding"]["fingerprint"] = "0" * 64
    elif fault == "plan_owner":
        c.fake.plans[c.result]["job_id"] = str(uuid4())
    elif fault == "plan_request":
        c.fake.plans[c.result]["request_sha256"] = "0" * 64
    elif fault == "recovered_stage":
        plan = {
            **c.plan,
            "explicit_recovery": {
                "policy": retry.POLICY,
                "original_stage_sha256": c.digest,
                "recovery_id": str(uuid4()),
            },
        }
        digest = _digest(plan)
        claim, result, token = "v3-stage-claim:" + digest, "v3-stage-result:" + digest, "9" * 32
        c.fake.plans.update({claim: plan, result: copy.deepcopy(plan)})
        c.fake.values[claim] = {"identity": digest, "claim_token": token}
        c.job.result[PENDING_KEY]["entries"] = {digest: {"claim_key": claim, "result_key": result, "token": token}}
        c.digest = digest
    elif fault == "two_pending":
        c.job.result[PENDING_KEY]["entries"]["1" * 64] = {
            "claim_key": "claim-other",
            "result_key": "result-other",
            "token": "2" * 32,
        }
    elif fault == "bad_ledger":
        c.job.params[retry.KEY] = {"policy": retry.POLICY, "entries": {}}
    digest = "0" * 64 if fault == "wrong_stage" else c.digest
    request = retry.UnknownStageRetryRequest(stage_sha256=digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True)
    before = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    with pytest.raises(ValueError):
        await retry.authorize_retry(None, c.job, actor, c.settings, request)
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == before


@pytest.fixture
def resume_case(owned_case, monkeypatch):
    c = owned_case
    c.job.stage, c.job.message = "interrupted", "held"
    c.job.completed_at, c.job.started_at = None, None
    c.job.result["resume_count"] = 4
    for i in range(13):
        c.fake.plans[f"cached-{i}"] = {"stage": f"cached-{i}"}
        c.fake.values[f"cached-{i}"] = {"response": {"cached": i}}
    monkeypatch.setattr(job_service, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=c.job))
    c.active_count = AsyncMock(return_value=0)
    monkeypatch.setattr(job_service, "count_active_ai_jobs", c.active_count)
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={"queue_position": 1}))
    monkeypatch.setattr("app.core.config.get_settings", lambda: c.settings)
    c.db = _CommitSession()
    c.dispatcher = job_service.InMemoryAIJobDispatcher()
    c.request = retry.UnknownStageRetryRequest(
        stage_sha256=c.digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True
    )
    return c


async def resume(c):
    return await job_service.resume_interrupted_ai_job(
        c.db,
        job=c.job,
        tenant_id=QA_TENANT,
        task_kwargs={"job_id": str(c.job.id)},
        active_limit=1,
        worker_concurrency=1,
        historical_estimate_seconds=60,
        dispatcher=c.dispatcher,
        retry_request=c.request,
        retry_actor_id=c.actor,
    )


@pytest.mark.asyncio
async def test_real_resume_authorizes_one_delivery_and_keeps_private_and_cached_history(resume_case):
    c = resume_case
    old_plans, old_values = copy.deepcopy(c.fake.plans), copy.deepcopy(c.fake.values)
    old_pending = copy.deepcopy(c.job.result[PENDING_KEY])
    resumed, metadata = await resume(c)
    job_service._lock_tenant_row.assert_awaited_once_with(c.db, QA_TENANT)
    job_service.get_ai_job.assert_awaited_once_with(c.db, str(c.job.id), tenant_id=str(QA_TENANT), for_update=True)
    assert resumed is c.job and resumed.status == "pending" and resumed.result["resume_count"] == 5
    assert metadata["queue_position"] == 1 and c.db.flushed == 1 and c.db.committed == 1
    assert PENDING_KEY not in resumed.result
    archived = retry.checked_ledger(resumed.params)["entries"][c.digest]
    assert archived["original_plan"] == c.plan and archived["pending_sha256"] == _digest(old_pending)
    assert archived["prior_outcome"] == archived["prior_usage"] == archived["prior_cost"] == "UNKNOWN"
    assert c.fake.plans == old_plans and c.fake.values == old_values
    assert len(c.dispatcher.submissions) == 1
    name, task_id, kwargs = c.dispatcher.submissions[0]
    assert name == "generate_course" and task_id == resumed.result["delivery_task_id"]
    assert kwargs == {"job_id": str(c.job.id)}
    after = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    with pytest.raises(job_service.AIJobSubmissionUnavailableError):
        await resume(c)
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == after
    assert len(c.dispatcher.submissions) == 1 and c.db.committed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["active_limit", "changed_approval", "inventory_unavailable"])
async def test_real_resume_rejection_precedes_mutation_commit_and_dispatch(resume_case, fault):
    c = resume_case
    if fault == "active_limit":
        c.active_count.return_value = 1
        expected = job_service.AIJobAdmissionLimitReachedError
    elif fault == "changed_approval":
        c.resolve_pins.side_effect = ValueError("approval changed")
        expected = job_service.AIJobSubmissionUnavailableError
    else:
        c.inventory.side_effect = RuntimeError("synthetic inventory unavailable")
        expected = RuntimeError
    before = tuple(copy.deepcopy(x) for x in (c.job.params, c.job.result, c.fake.plans, c.fake.values))
    with pytest.raises(expected):
        await resume(c)
    assert (c.job.params, c.job.result, c.fake.plans, c.fake.values) == before
    assert c.job.status == "interrupted" and c.db.flushed == c.db.committed == 0
    assert c.dispatcher.submissions == []
    if fault == "active_limit":
        c.resolve_pins.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_dispatch_keeps_queued_delivery_and_retry_ledger(resume_case):
    c = resume_case
    sent = []

    class UnknownDispatcher:
        def dispatch(self, name, *, task_id, kwargs):
            sent.append((name, task_id, kwargs))
            raise job_service.AIJobDispatchOutcomeUnknownError("synthetic")

    c.dispatcher = UnknownDispatcher()
    with pytest.raises(job_service.AIJobDispatchOutcomeUnknownError):
        await resume(c)
    assert c.db.committed == 1 and len(sent) == 1 and c.job.status == "pending"
    assert sent[0][1] == c.job.result["delivery_task_id"]
    assert PENDING_KEY not in c.job.result and c.digest in retry.checked_ledger(c.job.params)["entries"]
    assert c.claim in c.fake.values and c.result in c.fake.plans
