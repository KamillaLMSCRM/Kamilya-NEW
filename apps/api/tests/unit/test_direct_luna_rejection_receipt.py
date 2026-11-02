"""Actual client -> owned journal, with mocked transport and transactional repository."""
import json
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_direct_luna_owned_stage import options, setup


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
async def test_received_rejection_is_durable_but_cannot_replay_or_accept_content(monkeypatch, status):
    fake, journal, client, plan, validate = setup()
    transport = AsyncMock(side_effect=[
        json.dumps({"object": "response.input_tokens", "input_tokens": 12}),
        json.dumps({"model": "gpt-6-luna", "status": status,
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "error": {"message": "private-provider-error"},
                    "output": [{"content": [{"text": "private-partial-answer"}]}],
                    "usage": {"input_tokens": 12, "output_tokens": 128,
                              "output_tokens_details": {"reasoning_tokens": 96}}}),
    ])
    monkeypatch.setattr(client, "_post", transport)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    receipt = fake.job.result["v3_response_rejections"]["entries"][_digest(plan)]
    assert receipt == {"model": "gpt-6-luna", "status": status,
                       "reason": "max_output_tokens" if status == "incomplete" else "unknown",
                       "usage": {"input_tokens": 12, "output_tokens": 128,
                                 "cached_input_tokens": None, "reasoning_tokens": 96}}
    assert has_pending(fake.job.result) and "result" not in fake.values
    assert "private" not in json.dumps(fake.job.result)
    # Reconstruct the process-local client/journal, retaining only durable state.
    from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    cold = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id,
                               fake.sessions, verify_source=journal.verify_source)
    cold.repository, cold._lock_delivery = fake, fake._lock_delivery
    cold._owned_key, cold.read_owned_value_in_session = fake._owned_key, fake.read_owned_value_in_session
    other = DirectLunaResponsesClient(api_key="synthetic", tenant_id=client._scope[0],
                                     user_id=journal.user_id, job_id=journal.job_id)
    never = AsyncMock(side_effect=AssertionError("no repeated count or generation"))
    monkeypatch.setattr(other, "_post", never)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(cold, other, plan, validate))
    never.assert_not_awaited()
    assert transport.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,model", [("queued", "gpt-6-luna"), ("in_progress", "gpt-6-luna"),
                                          ("unrecognized-private", "gpt-6-luna"), (None, "gpt-6-luna"),
                                          ("incomplete", "wrong-model")])
async def test_unknown_or_nonterminal_envelope_cannot_create_rejection_receipt(monkeypatch, status, model):
    fake, journal, client, plan, validate = setup()
    transport = AsyncMock(side_effect=[json.dumps({"object": "response.input_tokens", "input_tokens": 12}),
                                      json.dumps({"model": model, "status": status})])
    monkeypatch.setattr(client, "_post", transport)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert has_pending(fake.job.result) and "v3_response_rejections" not in fake.job.result
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert transport.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source_drift", "lost_ack", "rollback", "foreign_actor", "claim_drift"])
async def test_rejection_persistence_faults_preserve_hold_and_never_retry(monkeypatch, fault):
    fake, journal, client, plan, validate = setup()
    after_generation = False
    sessions = fake.sessions

    def faulty_sessions():
        session = sessions()
        original_enter = session.__class__.__aenter__
        # Supply an independent context wrapper, keeping the fake transactional rollback semantics.
        class Wrapper:
            async def __aenter__(self):
                active = await original_enter(session)
                commit = active.commit
                async def checked_commit():
                    if after_generation and fault == "rollback":
                        raise TimeoutError("synthetic-before-commit")
                    await commit()
                active.commit = checked_commit
                return active
            async def __aexit__(self, *args):
                return await session.__aexit__(*args)
        return Wrapper()

    journal.sessions = faulty_sessions
    async def verify(_session, _job, _plan):
        return not (after_generation and fault == "source_drift")
    journal.verify_source = verify
    calls = []
    async def transport(endpoint, payload, **kwargs):
        nonlocal after_generation
        calls.append(endpoint)
        if endpoint.endswith("input_tokens"):
            return json.dumps({"object": "response.input_tokens", "input_tokens": 12})
        after_generation = True
        if fault == "lost_ack":
            fake.fail_ack = True
        elif fault == "foreign_actor":
            from uuid import uuid4
            fake.job.user_id = uuid4()
        elif fault == "claim_drift":
            fake.values["claim"] = {"identity": _digest(plan), "claim_token": "b" * 32}
        return json.dumps({"model": "gpt-6-luna", "status": "incomplete",
                           "incomplete_details": {"reason": "max_output_tokens"}})
    monkeypatch.setattr(client, "_post", transport)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert has_pending(fake.job.result) and "result" not in fake.values
    assert ("v3_response_rejections" in fake.job.result) is (fault == "lost_ack")
    fake.fail_ack = False
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_malformed_nullable_usage_and_unknown_reason_are_sanitized(monkeypatch):
    fake, journal, client, plan, validate = setup()
    transport = AsyncMock(side_effect=[json.dumps({"object": "response.input_tokens", "input_tokens": 12}),
        json.dumps({"model": "gpt-6-luna", "status": "incomplete",
                    "incomplete_details": {"reason": "private-unknown-reason"},
                    "usage": {"input_tokens": True, "output_tokens": 12,
                              "input_tokens_details": {"cached_tokens": -1},
                              "output_tokens_details": {"reasoning_tokens": 13}}})])
    monkeypatch.setattr(client, "_post", transport)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    receipt = fake.job.result["v3_response_rejections"]["entries"][_digest(plan)]
    assert receipt["reason"] == "unknown"
    assert receipt["usage"] == {"input_tokens": None, "output_tokens": 12,
                                "cached_input_tokens": None, "reasoning_tokens": None}
    assert "private" not in json.dumps(fake.job.result)


@pytest.mark.asyncio
async def test_actual_extraction_entrypoint_retains_nested_plan_rejection(monkeypatch):
    from app.modules.ai.v3.extraction_checkpoint import extract_once
    from tests.unit.test_v3_extraction_checkpoint import identity

    fake, journal, client, _, _ = setup()
    bound = identity(tenant_id=journal.tenant_id, job_id=journal.job_id)
    plan = {"schema": "v3-rule-extraction-checkpoint-v1", "identity": bound}
    transport = AsyncMock(side_effect=[json.dumps({"object": "response.input_tokens", "input_tokens": 12}),
                                      json.dumps({"model": "gpt-6-luna", "status": "incomplete"})])
    monkeypatch.setattr(client, "_post", transport)
    async def forbidden():
        raise AssertionError("legacy transport must not run")
    for _ in range(2):
        with pytest.raises(ExtractionOutcomeUnknownError):
            await extract_once(journal, bound, forbidden, direct_client=client,
                               direct_messages=[{"role": "user", "content": "synthetic"}])
    receipt = fake.job.result["v3_response_rejections"]["entries"][_digest(plan)]
    assert receipt["status"] == "incomplete" and receipt["reason"] == "unknown"
    assert has_pending(fake.job.result) and transport.await_count == 2
    assert not any(key.startswith("v3-result:") for key in fake.values)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant", "user", "job", "stage", "status"])
async def test_typed_rejection_for_wrong_scope_cannot_write_receipt(monkeypatch, field):
    from uuid import uuid4

    from app.modules.ai.direct_luna_responses_client import ResponsesRejectedError

    fake, journal, client, plan, validate = setup()
    async def post(endpoint, payload, **kwargs):
        assert endpoint.endswith("input_tokens")
        return json.dumps({"object": "response.input_tokens", "input_tokens": 12})
    monkeypatch.setattr(client, "_post", post)
    scope = (uuid4() if field == "tenant" else client._scope[0],
             uuid4() if field == "user" else journal.user_id,
             "another-job" if field == "job" else journal.job_id)
    stage = "f" * 64 if field == "stage" else _digest(plan)
    error = ResponsesRejectedError(scope, stage, ("queued" if field == "status" else "incomplete",
                                                 "unknown", None, None, None, None))
    invoke = AsyncMock(side_effect=error)
    monkeypatch.setattr(client, "invoke", invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert has_pending(fake.job.result) and "v3_response_rejections" not in fake.job.result
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    invoke.assert_awaited_once()
