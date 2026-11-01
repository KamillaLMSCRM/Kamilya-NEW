"""The worker must supply job-owned persistence and resolved route identity."""

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.modules.ai import pipeline
from app.modules.ai.v3 import service


@pytest.mark.asyncio
async def test_worker_supplies_job_scoped_journal_and_actual_route_fingerprint(monkeypatch):
    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import qa_luna_dev_route, worker_lesson_cycle

    tenant = UUID("11111111-1111-4111-8111-111111111111")
    state = pipeline.GenerationState(job_id="22222222-2222-4222-8222-222222222222")
    policy = SimpleNamespace(number=lambda _: 0.2)
    client = SimpleNamespace(cache_fingerprint=lambda: "a" * 64)
    captured = {}

    async def resolve():
        return policy

    async def qa_client(**kwargs):
        return client

    async def load_decisions(job_id, tenant_id, user_id, documents):
        assert job_id == state.job_id and tenant_id == tenant and user_id == tenant
        return ("trusted-decision",)

    class Journal:
        def __init__(self, tenant_id, job_id, session_factory):
            self.tenant_id = tenant_id
            self.job_id = job_id

    async def generate(corpus, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            diagnostics={"requires_source_review": True}, structure=None, assessment=None,
            content=SimpleNamespace(modules=[]),
        )

    monkeypatch.setattr(runtime, "resolve_runtime_settings", resolve)
    monkeypatch.setattr(runtime, "runtime_settings_scope", lambda _: nullcontext())
    monkeypatch.setattr(qa_luna_dev_route, "qa_luna_dev_client", qa_client)
    monkeypatch.setattr(worker_lesson_cycle, "WorkerCycleJournal", Journal)
    monkeypatch.setattr(service, "generate_v3_course_from_corpus", generate)
    monkeypatch.setattr(pipeline, "_load_owned_reference_decisions", load_decisions)

    await pipeline._run_v3_generation(state, SimpleNamespace(document_ids=(), tenant_id=str(tenant)), tenant_id=tenant, user_id=tenant,
                                      target_audience="", guidance=None, goals=None, max_total_lessons=None)
    assert captured["extraction_journal"].tenant_id == str(tenant)
    assert captured["extraction_journal"].job_id == state.job_id
    assert captured["route_fingerprint"] == "a" * 64
    assert captured["reference_decisions"] == ("trusted-decision",)
    assert state.server_source_review_required
