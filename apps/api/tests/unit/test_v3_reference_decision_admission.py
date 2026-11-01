"""Only authenticated, selected-source decisions can reach worker custody."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ai import pipeline
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.ai.v3.source_reference_decisions import admit_reference_decisions, hydrate_reference_decisions


def decision(document_id):
    return {"document_id": str(document_id), "source_revision": "document:" + "a" * 64,
            "converted_text_sha256": "b" * 64, "reference_start": 1, "reference_end": 4,
            "reference_exact": "ref", "target_start": 8, "target_end": 14,
            "target_exact": "target", "confirmed": True}


def test_authenticated_submission_binds_actor_tenant_and_selected_document():
    document_id, tenant_id, user_id = uuid4(), uuid4(), uuid4()
    req = AIGenerateRequest(documents=[document_id], reference_decisions=[decision(document_id)])
    records = admit_reference_decisions(req.reference_decisions, str(tenant_id), str(user_id), req.documents)
    assert records[0]["tenant_id"] == str(tenant_id) and records[0]["approved_by"] == str(user_id)
    assert records[0]["authority"] == "methodologist_confirmed"
    restored = hydrate_reference_decisions(records, str(tenant_id), str(user_id), [str(document_id)])
    assert len(restored) == 1 and restored[0].document_id == str(document_id)


def test_decisions_reject_unselected_docs_unconfirmed_and_authority_spoofing():
    doc, other = uuid4(), uuid4()
    with pytest.raises(ValidationError):
        AIGenerateRequest(documents=[doc], reference_decisions=[decision(other)])
    unconfirmed = decision(doc) | {"confirmed": False}
    with pytest.raises(ValidationError):
        AIGenerateRequest(documents=[doc], reference_decisions=[unconfirmed])
    with pytest.raises(ValidationError):
        AIGenerateRequest(documents=[doc], reference_decisions=[decision(doc) | {"confirmed": 1}])
    with pytest.raises(ValidationError):
        AIGenerateRequest(documents=[doc], reference_decisions=[decision(doc) | {"reference_start": True}])
    spoofed = decision(doc) | {"authority": "owner_chat"}
    with pytest.raises(ValidationError):
        AIGenerateRequest(documents=[doc], reference_decisions=[spoofed])


@pytest.mark.parametrize("field", ["tenant_id", "approved_by", "document_id", "authority"])
def test_worker_rejects_forged_job_decision_identity(field):
    doc, tenant, actor = uuid4(), uuid4(), uuid4()
    req = AIGenerateRequest(documents=[doc], reference_decisions=[decision(doc)])
    records = admit_reference_decisions(req.reference_decisions, str(tenant), str(actor), req.documents)
    records[0][field] = "forged"
    with pytest.raises(ValueError, match="reference_decision_"):
        hydrate_reference_decisions(records, str(tenant), str(actor), [str(doc)])


@pytest.mark.asyncio
async def test_worker_reads_only_owned_authoritative_job_decisions(monkeypatch):
    doc, tenant, actor = uuid4(), uuid4(), uuid4()
    req = AIGenerateRequest(documents=[doc], reference_decisions=[decision(doc)])
    records = admit_reference_decisions(req.reference_decisions, str(tenant), str(actor), req.documents)
    job = SimpleNamespace(user_id=actor, status="running", params={"documents": [str(doc)], "reference_decisions": records})
    session = SimpleNamespace(execute=AsyncMock())

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    get_job = AsyncMock(return_value=job)
    lock = AsyncMock()
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(pipeline, "lock_owned_delivery", lock)
    monkeypatch.setattr("app.modules.ai.job_service.get_ai_job", get_job)
    restored = await pipeline._load_owned_reference_decisions("job", tenant, actor, [str(doc)])
    assert len(restored) == 1 and restored[0].approved_by == str(actor)
    lock.assert_awaited_once_with(session, "job", str(tenant), require_running=True)
    get_job.assert_awaited_once_with(session, "job", tenant_id=str(tenant))
    with pytest.raises(pipeline.GenerationJobOwnerMismatchError):
        await pipeline._load_owned_reference_decisions("job", tenant, uuid4(), [str(doc)])
