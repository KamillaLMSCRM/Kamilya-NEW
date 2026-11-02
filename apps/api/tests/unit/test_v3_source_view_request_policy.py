"""Versioned source planning cannot mutate legacy requests or bypass ambiguity."""
import hashlib
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3 import service
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.prompts import LESSON_COGEN_SYSTEM_PROMPT, SOURCE_QUOTATION_VIEW_SUFFIX
from app.modules.ai.v3.reference_source_view import SourceReferenceReviewRequiredError
from app.modules.ai.v3.revision_policy import POLICY
from tests.unit.test_v3_reference_source_view import fixture


class CapturedError(RuntimeError):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [False, True])
async def test_legacy_prompt_bytes_are_preserved_and_new_suffix_is_scoped(fresh):
    seen = []
    async def capture(messages, response_format):
        seen.append(messages)
        raise CapturedError()
    pipeline = V3GenerationPipeline(capture, scoped_revision=fresh)
    with pytest.raises(CapturedError):
        await pipeline.generate_lesson_with_scenarios(module_title="m", lesson_theme="t", rules=[])
    assert hashlib.sha256(LESSON_COGEN_SYSTEM_PROMPT.encode()).hexdigest() == "7816c9c945a2045a8663ee6194bb595b78220a18aa01cff197d5f54051e317fe"
    expected = LESSON_COGEN_SYSTEM_PROMPT + (SOURCE_QUOTATION_VIEW_SUFFIX if fresh else "")
    assert seen[0][0]["content"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh,missing_target", [(True, False), (False, False), (True, True)])
async def test_service_uses_literal_view_before_author_and_holds_unresolved(monkeypatch, fresh, missing_target):
    corpus, model, decision = fixture()
    if missing_target:
        model = replace(model, rules=model.rules[:1])
    original = model.to_dict()
    authored = []
    class Pipeline:
        def __init__(self, *_args, **_kwargs):
            pass
        async def extract_rule_model(self, **_kwargs):
            return model
        async def generate_lesson_with_scenarios(self, **kwargs):
            authored.append(kwargs)
            raise CapturedError()
    monkeypatch.setattr(service, "V3GenerationPipeline", Pipeline)
    model_call = AsyncMock(side_effect=AssertionError("provider forbidden"))
    error = SourceReferenceReviewRequiredError if fresh and missing_target else CapturedError
    match = "source_reference_review_required" if fresh and missing_target else None
    with pytest.raises(error, match=match):
        await service.generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=model_call,
            reference_decisions=(decision,), revision_policy=POLICY if fresh else None)
    assert model.to_dict() == original
    model_call.assert_not_awaited()
    if missing_target:
        assert not authored
    elif fresh:
        rules = {rule.rule_id: rule for rule in authored[0]["rules"]}
        assert rules["r"].statement == model.rules[0].source_quote
        assert rules["r"].timing == ""
        assert len(authored[0]["reference_context"]) == 1
    else:
        assert authored[0]["rules"][0].statement == model.rules[0].statement


@pytest.mark.asyncio
async def test_source_review_pause_preserves_history_and_never_refunds(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from app.modules.ai import delivery_ownership, job_service, pipeline
    tenant, actor, document = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", AsyncMock(side_effect=SourceReferenceReviewRequiredError(("a"*64,))))
    refund = AsyncMock(side_effect=AssertionError("refund forbidden"))
    unknown = AsyncMock(side_effect=AssertionError("unknown provider fence forbidden"))
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", unknown)
    session = object()
    @asynccontextmanager
    async def sessions():
        yield session
    monkeypatch.setattr(pipeline, "async_session_factory", sessions)
    interrupt = AsyncMock(return_value=True)
    monkeypatch.setattr(job_service, "interrupt_claimed_generation_execution", interrupt)
    token = delivery_ownership.delivery_id.set("delivery-A")
    try:
        state = await pipeline.run_generation_pipeline("job", [str(document)], tenant_id=tenant, user_id=actor,
            source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source"})
    finally:
        delivery_ownership.delivery_id.reset(token)
    assert state.status == "interrupted" and state.errors == ["source_reference_review_required"]
    interrupt.assert_awaited_once_with(session, "job", str(tenant), "delivery-A", reason="source_reference_review_required")
    refund.assert_not_awaited()
    unknown.assert_not_awaited()
    job = SimpleNamespace(status="interrupted", params={"source_analysis": {"generation_engine": "evidence_v3"}},
                          result={}, errors=state.errors)
    assert not job_service.is_resumable_generation_job(job)
