"""Offline direct-owned diversity review through the real pending journal."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.v3.diversity_review import review_final_lesson
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import has_pending
from tests.unit.test_direct_luna_owned_stage import setup as direct_setup
from tests.unit.test_v3_diversity_review import setup as diversity_setup


def fixture():
    fake, journal, client, _, _ = direct_setup()
    args = diversity_setup()
    args.update(journal=journal, expected_tenant_id=journal.tenant_id,
                corpus=replace(args["corpus"], tenant_id=journal.tenant_id), direct_client=client)
    async def forbidden(_messages):
        raise AssertionError("legacy invoker forbidden")
    args["invoke"] = forbidden
    return fake, journal, client, args


def cold_journal(journal, fake):
    result = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id, fake.sessions,
                                 verify_source=journal.verify_source)
    result.repository = fake
    result._lock_delivery = fake._lock_delivery
    result._owned_key = fake._owned_key
    result.read_owned_value_in_session = fake.read_owned_value_in_session
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [False, True])
async def test_completed_cold_replay_and_known_malformed_hold(monkeypatch, malformed):
    fake, journal, client, args = fixture()
    fingerprint = []
    async def prepare(messages, **kwargs):
        assert await kwargs["ownership_checkpoint"]()
        fingerprint.append(json.loads(messages[1]["content"])["fingerprint"])
        return object()
    async def invoke(_cap, **kwargs):
        assert has_pending(fake.job.result) and await kwargs["ownership_checkpoint"]()
        response = {"fingerprint": fingerprint[-1], "status": "observed", "overlaps": [[1, 2]], "omissions": []}
        if malformed:
            response["overlaps"] = [[1, 1]]
        return SimpleNamespace(content=response)
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))
    first = await review_final_lesson(**args)
    assert first["status"] == ("unknown" if malformed else "review_required")
    assert not has_pending(fake.job.result)
    assert await review_final_lesson(**(args | {"journal": cold_journal(journal, fake)})) == first
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_ack_holds_without_duplicate_count_or_generation(monkeypatch):
    fake, journal, client, args = fixture()
    monkeypatch.setattr(client, "prepare", AsyncMock(return_value=object()))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=TimeoutError("synthetic lost acknowledgement")))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await review_final_lesson(**args)
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await review_final_lesson(**(args | {"journal": cold_journal(journal, fake)}))
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_changed_final_question_and_source_make_distinct_owned_stages(monkeypatch):
    _fake, _journal, client, args = fixture()
    fingerprints = []
    async def prepare(messages, **_kwargs):
        fingerprints.append(json.loads(messages[1]["content"])["fingerprint"])
        return object()
    async def invoke(_cap, **_kwargs):
        return SimpleNamespace(content={"fingerprint": fingerprints[-1], "status": "observed", "overlaps": [], "omissions": []})
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))
    await review_final_lesson(**args)
    lesson = args["lesson"]
    changed = replace(lesson, questions=(replace(lesson.questions[0], prompt="Different"), lesson.questions[1]))
    await review_final_lesson(**(args | {"lesson": changed}))
    rule = args["rules"][0]
    await review_final_lesson(**(args | {"rules": (replace(rule, conditions=("new condition",)),)}))
    assert len(set(fingerprints)) == 3 and client.prepare.await_count == client.invoke.await_count == 3


@pytest.mark.asyncio
async def test_document_body_and_revision_drift_hold_before_direct_call(monkeypatch):
    _fake, _journal, client, args = fixture()
    monkeypatch.setattr(client, "prepare", AsyncMock())
    monkeypatch.setattr(client, "invoke", AsyncMock())
    doc = args["corpus"].documents[0]
    for changed in (replace(doc, source_text="different"), replace(doc, source_revision="other")):
        result = await review_final_lesson(**(args | {"corpus": replace(args["corpus"], documents=(changed,))}))
        assert result["status"] == "unknown" and result["reason"] == "source_manifest_unavailable"
    client.prepare.assert_not_awaited()
    client.invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_unknown_blocks_changed_request_without_another_count(monkeypatch):
    fake, _journal, client, args = fixture()
    monkeypatch.setattr(client, "prepare", AsyncMock(return_value=object()))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=TimeoutError("unknown")))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await review_final_lesson(**args)
    lesson = args["lesson"]
    changed = replace(lesson, questions=(replace(lesson.questions[0], prompt="Different"), lesson.questions[1]))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await review_final_lesson(**(args | {"lesson": changed}))
    assert has_pending(fake.job.result)
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_source_verifier_denial_after_count_holds_before_generation(monkeypatch):
    fake, journal, client, args = fixture()
    async def prepare(_messages, **_kwargs):
        async def deny(_session, _job, _plan):
            return False
        journal.verify_source = deny
        return object()
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock())
    with pytest.raises(ExtractionOutcomeUnknownError, match="source_unverified"):
        await review_final_lesson(**args)
    client.invoke.assert_not_awaited()
    assert not has_pending(fake.job.result)


@pytest.mark.asyncio
async def test_finalize_ack_loss_recovers_only_by_owned_readback(monkeypatch):
    fake, journal, client, args = fixture()
    fingerprints = []
    async def prepare(messages, **_kwargs):
        fingerprints.append(json.loads(messages[1]["content"])["fingerprint"])
        return object()
    async def invoke(_cap, **_kwargs):
        fake.fail_ack = True
        return SimpleNamespace(content={"fingerprint": fingerprints[-1], "status": "observed", "overlaps": [], "omissions": []})
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await review_final_lesson(**args)
    fake.fail_ack = False
    result = await review_final_lesson(**(args | {"journal": cold_journal(journal, fake)}))
    assert result["status"] == "review_required" and not has_pending(fake.job.result)
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()
