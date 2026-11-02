"""Fake transaction evidence only; no live database or provider."""
import socket
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import httpx
import pytest

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.final_save_contract import INTENT_KEY
from app.modules.ai.v3.final_save_owned_checkpoint import checkpoint_final_output
from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY
from app.modules.ai.v3.owned_route_binding import POLICY as ROUTE_POLICY
from app.modules.ai.v3.owned_source_context import OwnedSourceContext
from app.modules.ai.v3.pending_stage_transactions import has_pending
from tests.unit.test_pending_stage_transactions import TxJournal
from tests.unit.test_v3_final_save_readback import fixture


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "Client", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)


def setup(monkeypatch):
    data = fixture()
    intent, job = data["intent"], data["job"]
    journal = TxJournal()
    journal.tenant_id, journal.job_id = intent["tenant_id"], intent["job_id"]
    journal.job = job
    job.status, job.course_id = "running", None
    job.result = {"delivery_task_id": intent["delivery_id"], ROUTE_KEY:
                  {"policy": ROUTE_POLICY, "fingerprint": intent["route_fingerprint"]}}
    job.params = {"documents": data["state"].source_document_ids,
                  "source_analysis": data["state"].source_analysis}
    context = OwnedSourceContext(data["source_corpus"], journal, UUID(intent["tenant_id"]),
                                 UUID(intent["user_id"]), intent["job_id"],
                                 tuple(data["state"].source_document_ids))
    async def verified(*_args):
        return True
    monkeypatch.setattr(OwnedSourceContext, "verify_locked", verified)
    return data, journal, context


@pytest.mark.asyncio
async def test_atomic_checkpoint_cold_replay_and_lost_ack(monkeypatch):
    data, journal, context = setup(monkeypatch)
    kwargs = dict(journal=journal, context=context, state=data["state"], intent=data["intent"])
    journal.fail_ack = True
    with pytest.raises(ExtractionOutcomeUnknownError):
        await checkpoint_final_output(**kwargs)
    assert has_pending(journal.job.result) and INTENT_KEY in journal.job.result and len(journal.values) == 1
    before = deepcopy((journal.values, journal.job.result))
    journal.fail_ack = False
    await checkpoint_final_output(**kwargs)
    assert (journal.values, journal.job.result) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["state_course", "job_course", "owner", "route", "source", "checkpoint"])
async def test_changed_identity_or_output_is_held(monkeypatch, drift):
    data, journal, context = setup(monkeypatch)
    kwargs = dict(journal=journal, context=context, state=data["state"], intent=data["intent"])
    if drift == "state_course":
        data["state"].course_id = "foreign"
    if drift == "job_course":
        journal.job.course_id = UUID(int=2)
    if drift == "owner":
        journal.job.user_id = UUID(int=3)
    if drift == "route":
        journal.job.params["source_analysis"] = {}
    if drift == "source":
        doc = replace(context.corpus.documents[0], source_text="changed")
        context.corpus = replace(context.corpus, documents=(doc,))
    if drift == "checkpoint":
        await checkpoint_final_output(**kwargs)
        next(iter(journal.values.values()))["output"]["content"]["title"] = "changed"
    with pytest.raises(ExtractionOutcomeUnknownError):
        await checkpoint_final_output(**kwargs)
    if drift != "checkpoint":
        assert not journal.values
