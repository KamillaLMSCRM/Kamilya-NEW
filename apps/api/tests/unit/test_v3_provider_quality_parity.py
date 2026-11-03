import socket
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, V3Course
from app.modules.ai.v3.owned_source_context import OwnedSourceContext
from app.modules.ai.v3.revision_policy import POLICY
from app.modules.ai.v3.service import _review_final_diversity, generate_v3_course_from_corpus
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal
from tests.unit.test_v3_primary_source_manifest import sample


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    monkeypatch.setattr(httpx, "Client", deny)


def ordinary_context():
    corpus, rule = sample()
    tenant, actor, job = uuid4(), uuid4(), str(uuid4())
    corpus = replace(corpus, tenant_id=str(tenant))
    journal = WorkerCycleJournal(str(tenant), job, lambda: None)
    context = OwnedSourceContext(corpus, journal, tenant, actor, job, tuple(corpus.document_ids))
    journal.expected_revision_policy = POLICY
    journal.expected_revision_actor = actor
    journal.expected_revision_source = context
    return corpus, rule, journal, context


@pytest.mark.asyncio
async def test_ordinary_final_review_requires_owned_source_and_keeps_unknown_hold(monkeypatch):
    from app.modules.ai.v3 import diversity_review
    from app.modules.ai.v3.models import V3Lesson

    corpus, rule, journal, context = ordinary_context()
    reviewer = AsyncMock(return_value={"status": "unknown", "reason": "synthetic"})
    monkeypatch.setattr(diversity_review, "review_final_lesson", reviewer)
    signals, violations = [], []
    args = dict(policy=None, lessons=[V3Lesson("l", "", "", "body", ("r1",))], groups=[("g", (rule,))],
        corpus=corpus, journal=journal, source_context=None, direct_client=None, source_sha256="a" * 64,
        route_fingerprint="b" * 64, invoke=AsyncMock(), max_tokens=8192, cancellation_callback=None,
        signals=signals, violations=violations, allow_repair=True)
    await _review_final_diversity(**args)
    reviewer.assert_not_awaited()
    await _review_final_diversity(**(args | {"policy": "qa-direct-luna-explanation-v2"}), revision_policy=POLICY)
    reviewer.assert_not_awaited()
    await _review_final_diversity(**args, revision_policy=POLICY)
    reviewer.assert_awaited_once()
    assert reviewer.await_args.kwargs["expected_document_ids"] == context.selection
    assert reviewer.await_args.kwargs["direct_client"] is None and violations
    journal.expected_revision_source = None
    with pytest.raises(ExtractionOutcomeUnknownError):
        await _review_final_diversity(**args, revision_policy=POLICY)
    assert reviewer.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [True, False])
async def test_ordinary_service_quality_is_gated_by_fresh_revision(monkeypatch, fresh):
    from app.modules.ai.v3 import diversity_review, exact_duplicate_review, partitioned_extraction, service

    corpus, rule, journal, _ = ordinary_context()
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "lessons": [{"lesson_id": "l",
        "title": "t", "module_title": "m", "content": "Lesson", "covered_rule_ids": ["r1"],
        "cases": [{"case_id": "c1", "rule_id": "r1", "learning_objective": "x", "variants": [{
            "variant_id": "v1", "scenario_premise": "S", "prompt": "Question?",
            "correct_option": {"text": "A"}, "distractor_pool": [{"text": "B"}, {"text": "C"}, {"text": "D"}],
            "source_quote": rule.source_quote}]}]}]}).lessons[0]
    async def extraction(*_args, **_kwargs):
        return DocumentRuleModel("t", "s", (rule,)), []
    monkeypatch.setattr(partitioned_extraction, "extract_partitioned_rule_model", extraction)
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_a, **_kw: [CurriculumGroup("g", "topic", "s", (rule,))])
    generated = AsyncMock(return_value=lesson)
    monkeypatch.setattr(service.V3GenerationPipeline, "generate_lesson_with_scenarios", generated)
    original_init = service.V3GenerationPipeline.__init__
    flags = []
    def record_init(instance, *args, **kwargs):
        flags.append(kwargs.get("explanation_consistency"))
        original_init(instance, *args, **kwargs)
    monkeypatch.setattr(service.V3GenerationPipeline, "__init__", record_init)
    monkeypatch.setattr(service.V3GenerationPipeline, "review_answer", AsyncMock(return_value={"verdict": "COMPLETE", "claims": []}))
    monkeypatch.setattr(service, "_bind_rendered_quote_candidates", lambda *_a: (lesson, []))
    monkeypatch.setattr(service, "_nonliteral_case_citation_ids", lambda *_a: ["v1"])
    reviewer = AsyncMock(return_value={"status": "unknown", "reason": "synthetic"})
    monkeypatch.setattr(diversity_review, "review_final_lesson", reviewer)
    duplicates = []
    monkeypatch.setattr(exact_duplicate_review, "has_cross_lesson_duplicate", lambda lessons: duplicates.append(lessons) or True)
    adapter = service.v3_course_to_generation_artifacts
    adapter_args = []
    def capture_adapter(*args, **kwargs):
        adapter_args.append(kwargs)
        return adapter(*args, **kwargs)
    monkeypatch.setattr(service, "v3_course_to_generation_artifacts", capture_adapter)
    artifacts = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=AsyncMock(),
        extraction_journal=journal, route_fingerprint="b" * 64, revision_policy=POLICY if fresh else None)
    assert flags and all(value is fresh for value in flags)
    if fresh:
        reviewer.assert_awaited_once()
        assert len(duplicates) == 1 and any("совпадают" in item for item in artifacts.diagnostics["violations"])
        assert adapter_args[0]["source_corpus"] is corpus and adapter_args[0]["exact_narrative_facts"] is True
    else:
        reviewer.assert_not_awaited()
        assert not duplicates and "source_corpus" not in adapter_args[0]
