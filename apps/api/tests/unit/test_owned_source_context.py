import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_source_context import load_owned_source_context


@pytest.fixture
def setup(monkeypatch):
    from app.modules.ai.v3 import owned_source_context as module
    tenant, user, doc_id = uuid4(), uuid4(), uuid4()
    doc = DirectSourceDocument(doc_id=str(doc_id), title="x", filename="x", category="general",
        source_revision="document:" + "a" * 64, chunks=(), source_text="synthetic")
    corpus = DirectSourceCorpus(tenant_id=str(tenant), documents=(doc,), total_chars=9, total_chunks=0)
    job = SimpleNamespace(id="job", tenant_id=tenant, user_id=user, status="running",
        params={"documents": [str(doc_id)], "source_analysis": {"generation_engine": "evidence_v3"}})
    row = SimpleNamespace(id=doc_id, tenant_id=tenant, lifecycle_status="active", content_sha256="a" * 64)
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def scalar(self, statement): return row
    journal = SimpleNamespace(tenant_id=str(tenant), job_id="job", sessions=Session)
    async def locked(_session, _journal, actor):
        if actor != job.user_id or job.status != "running":
            raise ValueError("owner or cancellation")
        return job
    loader = AsyncMock(return_value=corpus)
    monkeypatch.setattr(module, "_locked_job", locked)
    monkeypatch.setattr(module, "load_direct_source_corpus", loader)
    return tenant, user, journal, job, row, corpus, loader


@pytest.mark.asyncio
async def test_canonical_loader_only_and_exact_selection(setup):
    tenant, user, journal, job, _, corpus, loader = setup
    context = await load_owned_source_context(journal=journal, tenant_id=tenant, user_id=user, job_id="job")
    loader.assert_awaited_once_with(job.params["documents"], tenant_id=tenant)
    assert context.corpus is corpus and "synthetic" not in repr(context)
    plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": str(tenant), "job_id": "job",
            "source_sha256": hashlib.sha256(b"synthetic").hexdigest()}
    assert await context.verify_before_send(plan) is True


@pytest.mark.asyncio
async def test_client_corpus_cannot_be_passed_at_entry(setup):
    tenant, user, journal, _, _, corpus, loader = setup
    with pytest.raises(TypeError):
        await load_owned_source_context(journal=journal, tenant_id=tenant, user_id=user, job_id="job", corpus=corpus)
    loader.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["owner", "cancel", "revision", "selection"])
async def test_drift_during_loader_fails_closed(setup, drift):
    tenant, user, journal, job, row, corpus, loader = setup
    async def changed(*args, **kwargs):
        if drift == "owner":
            job.user_id = uuid4()
        if drift == "cancel":
            job.status = "cancelled"
        if drift == "revision":
            row.content_sha256 = "b" * 64
        if drift == "selection":
            job.params["documents"] = [str(uuid4())]
        return corpus
    loader.side_effect = changed
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_owned_source_unverified") as error:
        await load_owned_source_context(journal=journal, tenant_id=tenant, user_id=user, job_id="job")
    assert error.value.__context__ is None
