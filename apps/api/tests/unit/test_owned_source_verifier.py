import hashlib
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.owned_source_verifier import build_owned_source_verifier


def sha(value): return hashlib.sha256(value.encode()).hexdigest()


def setup():
    tenant, user, doc_id = uuid4(), uuid4(), uuid4()
    doc = DirectSourceDocument(doc_id=str(doc_id), title="synthetic", filename="x", category="general",
        source_revision="document:" + "a" * 64, chunks=(), source_text="synthetic text")
    corpus = DirectSourceCorpus(tenant_id=str(tenant), documents=(doc,), total_chars=14, total_chunks=0)
    job = SimpleNamespace(id="job", tenant_id=tenant, user_id=user, status="running",
        params={"documents": [str(doc_id)], "source_analysis": {"generation_engine": "evidence_v3"}})
    row = SimpleNamespace(id=doc_id, tenant_id=tenant, lifecycle_status="active", content_sha256="a" * 64)
    plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": str(tenant), "job_id": "job",
            "source_sha256": sha("synthetic text")}
    class Session:
        async def scalar(self, statement): return row
    return tenant, user, corpus, job, row, plan, Session()


@pytest.mark.asyncio
async def test_exact_stage_and_extraction_source_accepted():
    tenant, user, corpus, job, _, plan, session = setup()
    verify = build_owned_source_verifier(corpus=corpus, tenant_id=tenant, user_id=user, job_id="job")
    assert await verify(session, job, plan) is True
    doc = corpus.documents[0]
    identity = {"tenant_id": str(tenant), "job_id": "job", "document_id": doc.doc_id,
                "source_revision": doc.source_revision, "source_sha256": sha(doc.source_text),
                "unit_start": "0", "unit_end": "9", "unit_sha256": sha("synthetic")}
    assert await verify(session, job, {"schema": "v3-rule-extraction-checkpoint-v1", "identity": identity}) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["hash", "inactive", "foreign_row", "order", "duplicate", "source", "job", "engine", "tenant", "user"])
async def test_source_drift_or_foreign_scope_rejected(change):
    tenant, user, corpus, job, row, plan, session = setup()
    if change == "hash":
        row.content_sha256 = "b" * 64
    if change == "inactive":
        row.lifecycle_status = "deleted"
    if change == "foreign_row":
        row.tenant_id = uuid4()
    if change == "order":
        job.params["documents"] = [str(uuid4())]
    if change == "duplicate":
        job.params["documents"] *= 2
    if change == "source":
        corpus = replace(corpus, documents=(replace(corpus.documents[0], source_text="changed"),))
    if change == "job":
        job.id = "foreign"
    if change == "engine":
        job.params["source_analysis"]["generation_engine"] = "evidence_v2"
    if change == "tenant":
        job.tenant_id = uuid4()
    if change == "user":
        job.user_id = uuid4()
    verify = build_owned_source_verifier(corpus=corpus, tenant_id=tenant, user_id=user, job_id="job")
    assert await verify(session, job, plan) is False
