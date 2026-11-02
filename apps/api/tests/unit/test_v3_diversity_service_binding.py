import socket
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, DIRECT_POLICY_V2
from app.modules.ai.v3.service import _review_final_diversity, generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_primary_source_manifest import sample


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network forbidden in offline service test")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(httpx, "AsyncClient", blocked)
    monkeypatch.setattr(httpx, "Client", blocked)


def test_offline_guard_blocks_network_entry_points():
    entries = (lambda: socket.socket.connect(None, ("127.0.0.1", 1)),
               lambda: socket.socket.connect_ex(None, ("127.0.0.1", 1)),
               lambda: socket.create_connection(("127.0.0.1", 1)),
               lambda: httpx.AsyncClient(), lambda: httpx.Client())
    for entry in entries:
        with pytest.raises(AssertionError, match="network forbidden"):
            entry()


@pytest.mark.asyncio
async def test_forged_source_context_is_rejected_before_generation():
    _, journal, client, _, _ = setup()
    corpus, _ = sample()
    corpus = replace(corpus, tenant_id=journal.tenant_id)
    forged = SimpleNamespace(corpus=corpus, journal=journal, selection=("d1",),
        tenant_id=journal.tenant_id, user_id=journal.user_id, job_id=journal.job_id)
    with pytest.raises(ExtractionOutcomeUnknownError, match="owned_context_unverified"):
        await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=client,
            extraction_journal=journal, direct_client=client, authenticated_qa_policy=DIRECT_POLICY,
            owned_source_context=forged)


@pytest.mark.asyncio
async def test_owned_context_selection_cannot_disagree_with_corpus():
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext

    _, journal, client, _, _ = setup()
    corpus, _ = sample()
    corpus = replace(corpus, tenant_id=journal.tenant_id)
    context = OwnedSourceContext(corpus, journal, UUID(journal.tenant_id), journal.user_id,
                                 journal.job_id, ("different",))
    with pytest.raises(ExtractionOutcomeUnknownError, match="owned_context_unverified"):
        await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=client,
            extraction_journal=journal, direct_client=client, authenticated_qa_policy=DIRECT_POLICY,
            owned_source_context=context)


@pytest.mark.asyncio
async def test_final_two_lessons_and_v2_no_review(monkeypatch):
    from app.modules.ai.v3 import diversity_review
    from app.modules.ai.v3.models import V3Lesson

    _, journal, client, _, _ = setup()
    corpus, rule = sample()
    corpus = replace(corpus, tenant_id=journal.tenant_id)
    reviewer = AsyncMock(side_effect=[
        {"status": "review_required", "overlaps": [], "omissions": []},
        {"status": "unknown", "reason": "missing"},
    ])
    monkeypatch.setattr(diversity_review, "review_final_lesson", reviewer)
    repaired = V3Lesson("one", "", "", "repaired final", ("r1",))
    second = V3Lesson("two", "", "", "second", ("r1",))
    signals, violations = [], []
    args = dict(lessons=[repaired, second], groups=[("g1", (rule,)), ("g2", ())], corpus=corpus,
        journal=journal, source_context=SimpleNamespace(selection=("d1",)), direct_client=client,
        source_sha256="a" * 64, route_fingerprint="b" * 64, invoke=AsyncMock(), max_tokens=8192,
        cancellation_callback=None, signals=signals, violations=violations)
    await _review_final_diversity(policy=DIRECT_POLICY_V2, **args)
    reviewer.assert_not_awaited()
    await _review_final_diversity(policy=DIRECT_POLICY, **args)
    assert reviewer.await_count == 2
    assert reviewer.await_args_list[0].kwargs["lesson"] is repaired
    assert reviewer.await_args_list[0].kwargs["rules"] == (rule,)
    assert reviewer.await_args_list[1].kwargs["rules"] == ()
    assert reviewer.await_args_list[0].kwargs["expected_document_ids"] == ("d1",)
    assert len(signals) == 2 and len(violations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [DIRECT_POLICY, DIRECT_POLICY_V2])
async def test_full_generation_dispatches_final_repaired_lesson(monkeypatch, policy):
    from app.modules.ai.v3 import diversity_review, partitioned_extraction, service
    from app.modules.ai.v3.assessment_projection import project_lesson_questions
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, V3Course
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext

    _, journal, client, _, _ = setup()
    corpus, rule = sample()
    corpus = replace(corpus, tenant_id=journal.tenant_id)
    context = OwnedSourceContext(corpus, journal, UUID(journal.tenant_id), journal.user_id, journal.job_id, ("d1",))
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "lessons": [{"lesson_id": "l",
        "title": "t", "module_title": "m", "content": "Lesson", "covered_rule_ids": ["r1"],
        "cases": [{"case_id": "c1", "rule_id": "r1", "learning_objective": "x", "variants": [{
            "variant_id": "v1", "scenario_premise": "S", "prompt": "Original?",
            "correct_option": {"text": "A"}, "distractor_pool": [{"text": "B"}, {"text": "C"}, {"text": "D"}],
            "source_quote": rule.source_quote}]}]}]}).lessons[0]
    v = replace(lesson.cases[0].variants[0], prompt="Repaired final?")
    repaired = replace(lesson, cases=(replace(lesson.cases[0], variants=(v,)),))
    group = CurriculumGroup("g1", "topic", "s", (rule,))
    async def extraction(*_a, **_kw):
        return DocumentRuleModel("t", "s", (rule,)), []
    monkeypatch.setattr(partitioned_extraction, "extract_partitioned_rule_model", extraction)
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_a, **_kw: [group])
    monkeypatch.setattr(service.V3GenerationPipeline, "generate_lesson_with_scenarios", AsyncMock(return_value=lesson))
    monkeypatch.setattr(service.V3GenerationPipeline, "review_answer", AsyncMock(return_value={"verdict": "COMPLETE", "claims": []}))
    monkeypatch.setattr(service, "_bind_rendered_quote_candidates", lambda *_a: (repaired, []))
    monkeypatch.setattr(service, "_nonliteral_case_citation_ids", lambda *_a: ["v1"])
    reviewer = AsyncMock(return_value={"status": "unknown", "reason": "incomplete"})
    monkeypatch.setattr(diversity_review, "review_final_lesson", reviewer)
    artifacts = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=client,
        extraction_journal=journal, route_fingerprint="b" * 64, direct_client=client,
        authenticated_qa_policy=policy, owned_source_context=context)
    if policy == DIRECT_POLICY_V2:
        reviewer.assert_not_awaited()
    else:
        reviewer.assert_awaited_once()
        seen = reviewer.await_args.kwargs
        assert seen["lesson"] == repaired and seen["rules"] == (rule,)
        assert seen["expected_document_ids"] == context.selection
        assert project_lesson_questions(seen["lesson"]) == artifacts.assessment.assessments[0].mcq
        assert any("разнообразие вопросов" in item for item in artifacts.diagnostics["violations"])


@pytest.mark.asyncio
async def test_final_diversity_repair_preserves_prior_review_and_hold(monkeypatch):
    from app.modules.ai.v3 import diversity_repair_promotion, diversity_repair_selection, diversity_review
    from tests.unit.test_v3_diversity_repair_selection import setup as lesson_setup

    _, journal, client, _, _ = setup()
    data = lesson_setup()
    corpus = replace(data["corpus"], tenant_id=journal.tenant_id)
    lesson, rule = data["lesson"], data["rules"][0]
    case = lesson.cases[0]
    candidate = replace(lesson, cases=(replace(case, variants=(case.variants[0],
        replace(case.variants[1], prompt="new question"))),))
    reviewer = AsyncMock(return_value={"status": "review_required", "overlaps": [[1, 2]],
        "omissions": [{"rule_id": "r1", "exact_quote": rule.source_quote}]})
    selector = AsyncMock(return_value=object())
    repair = AsyncMock(return_value=(candidate, True))
    monkeypatch.setattr(diversity_review, "review_final_lesson", reviewer)
    monkeypatch.setattr(diversity_repair_selection, "select_owned_candidate", selector)
    monkeypatch.setattr(diversity_repair_promotion, "staged_diversity_repair", repair)
    lessons, signals, violations = [lesson], [], []
    records = {lesson.lesson_id: {"verdict": "PASS", "parts": ["original"]}}
    args = dict(lessons=lessons, groups=[("g", (rule,))], corpus=corpus, journal=journal,
        source_context=SimpleNamespace(selection=("d1",)), direct_client=client,
        source_sha256="a" * 64, route_fingerprint="b" * 64, invoke=AsyncMock(), max_tokens=8192,
        cancellation_callback=None, signals=signals, violations=violations, repair_contexts=[((), ())],
        review_records=records, allow_repair=True)
    await _review_final_diversity(policy=DIRECT_POLICY_V2, **args)
    selector.assert_not_awaited()
    await _review_final_diversity(policy=DIRECT_POLICY, **args)
    assert lessons == [candidate] and violations
    assert records[lesson.lesson_id]["verdict"] == "NEEDS_REVISION"
    assert records[lesson.lesson_id]["parts"] == ["original"]
    assert selector.await_args.kwargs["selected_index"] == 2
    repair.assert_awaited_once()



@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [DIRECT_POLICY, DIRECT_POLICY_V2])
async def test_opt_in_unknown_aborts_before_later_model_or_count(monkeypatch, policy):
    from app.modules.ai.v3 import diversity_review, partitioned_extraction, service
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from tests.unit.test_v3_diversity_repair_selection import setup as lesson_setup

    fake, journal, client, _, _ = setup()
    data = lesson_setup()
    corpus = replace(data["corpus"], tenant_id=journal.tenant_id)
    rule, lesson = data["rules"][0], data["lesson"]
    context = OwnedSourceContext(corpus, journal, UUID(journal.tenant_id), journal.user_id, journal.job_id, ("d1",))
    async def extraction(*_args, **_kwargs):
        return DocumentRuleModel("t", "s", (rule,)), []
    monkeypatch.setattr(partitioned_extraction, "extract_partitioned_rule_model", extraction)
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_a, **_kw: [CurriculumGroup("g", "t", "s", (rule,))])
    monkeypatch.setattr(service.V3GenerationPipeline, "generate_lesson_with_scenarios", AsyncMock(return_value=lesson))
    monkeypatch.setattr(service, "_bind_rendered_quote_candidates", lambda *_a: (lesson, []))
    monkeypatch.setattr(service, "_nonliteral_case_citation_ids", lambda *_a: [])
    monkeypatch.setattr(service, "_repair_option_shortcuts", AsyncMock(return_value=(lesson, False)))
    monkeypatch.setattr("app.modules.ai.v3.explanation_repair.repair_order_dependent_explanations", AsyncMock(return_value=(lesson, False)))
    monkeypatch.setattr(service.V3GenerationPipeline, "review_lesson", AsyncMock(side_effect=ExtractionOutcomeUnknownError("held")))
    review = AsyncMock()
    prepare = AsyncMock()
    monkeypatch.setattr(diversity_review, "review_final_lesson", review)
    monkeypatch.setattr(client, "prepare", prepare)
    async def generate():
        return await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=client,
            extraction_journal=journal, route_fingerprint="b" * 64, direct_client=client,
            authenticated_qa_policy=policy, owned_source_context=context, allow_unreviewed_on_unknown=True)
    if policy == DIRECT_POLICY:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate()
    else:
        artifacts = await generate()
        assert artifacts.diagnostics["validation_report"]["semantic_reviews"][lesson.lesson_id]["verdict"] == "ERROR"
    review.assert_not_awaited()
    prepare.assert_not_awaited()
    assert not fake.plans


@pytest.mark.asyncio
async def test_dependency_context_holds_before_initial_diversity_call(monkeypatch):
    from app.modules.ai.v3 import diversity_review
    from tests.unit.test_v3_diversity_repair_selection import setup as lesson_setup

    _, journal, client, _, _ = setup()
    data = lesson_setup()
    corpus = replace(data["corpus"], tenant_id=journal.tenant_id)
    reviewer = AsyncMock()
    monkeypatch.setattr(diversity_review, "review_final_lesson", reviewer)
    signals, violations = [], []
    await _review_final_diversity(policy=DIRECT_POLICY, lessons=[data["lesson"]], groups=[("g", data["rules"])],
        corpus=corpus, journal=journal, source_context=SimpleNamespace(selection=("d1",)), direct_client=client,
        source_sha256="a" * 64, route_fingerprint="b" * 64, invoke=AsyncMock(), max_tokens=8192,
        cancellation_callback=None, signals=signals, violations=violations,
        repair_contexts=[((), ("unresolved",))], review_records={}, allow_repair=True)
    reviewer.assert_not_awaited()
    assert signals and violations



@pytest.mark.asyncio
async def test_context_review_binds_selection_and_rejects_context_drift(monkeypatch):
    import json

    from app.modules.ai.v3 import diversity_review
    from app.modules.ai.v3.diversity_repair_selection import select_candidate
    from tests.unit.test_v3_diversity_repair_selection import setup as lesson_setup

    _, journal, client, _, _ = setup()
    data = lesson_setup()
    corpus = replace(data["corpus"], tenant_id=journal.tenant_id)
    primary, lesson = data["rules"], data["lesson"]
    text = corpus.documents[0].source_text
    quote = "Далее выполняется запись."
    start = text.index(quote)
    context = replace(primary[0], rule_id="dependency", statement=quote, source_quote=quote,
                      source_start=start, source_end=start + len(quote))
    seen = []
    async def stage(_journal, **kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        seen.append(request)
        return {"fingerprint": request["fingerprint"], "status": "observed", "overlaps": [[1, 2]],
                "omissions": [{"rule_id": "r1", "exact_quote": primary[0].source_quote}]}
    monkeypatch.setattr(diversity_review, "stage_once", stage)
    observed = await diversity_review.review_final_lesson(lesson=lesson, corpus=corpus, rules=primary,
        expected_tenant_id=journal.tenant_id, expected_document_ids=("d1",), journal=journal,
        group_id="diversity:g", source_sha256="a" * 64, route_fingerprint="b" * 64,
        invoke=AsyncMock(), direct_client=client, context_rules=(context,))
    args = dict(lesson=lesson, corpus=corpus, rules=primary, expected_tenant_id=journal.tenant_id,
        expected_document_ids=("d1",), observation=observed, selected_index=2, context_rules=(context,))
    selected = select_candidate(**args)
    assert selected is not None
    import hashlib

    from app.modules.ai.v3.diversity_owned_selection_guard import build_owned_selection_guard
    from app.modules.ai.v3.stage_checkpoint import _digest

    async def saved(_session, _key, plan):
        response = {"fingerprint": seen[0]["fingerprint"], "status": "observed", "overlaps": [[1, 2]],
                    "omissions": [{"rule_id": "r1", "exact_quote": primary[0].source_quote}]}
        return {"identity": _digest(plan), "response": response, "response_sha256": _digest(response)}
    journal.read_owned_value_in_session = saved
    guard = build_owned_selection_guard(lesson=lesson, corpus=corpus, rules=primary, journal=journal,
        expected_document_ids=("d1",), review_group_id="diversity:g",
        source_sha256=hashlib.sha256(text.encode()).hexdigest(), route_fingerprint="b" * 64,
        selected=selected, context_rules=(context,))
    assert await guard(object(), object(), {}) is True
    stale = build_owned_selection_guard(lesson=lesson, corpus=corpus, rules=primary, journal=journal,
        expected_document_ids=("d1",), review_group_id="diversity:g",
        source_sha256=hashlib.sha256(text.encode()).hexdigest(), route_fingerprint="b" * 64,
        selected=selected, context_rules=(replace(context, statement="changed"),))
    assert await stale(object(), object(), {}) is False
    assert seen[0]["primary_sources"][0]["rule_id"] == "r1"
    assert seen[0]["context_source_manifest"]["fragments"][0]["rule_id"] == "dependency"
    assert select_candidate(**(args | {"context_rules": ()})) is None
    assert select_candidate(**(args | {"context_rules": (replace(context, statement="changed"),)})) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', [DIRECT_POLICY, DIRECT_POLICY_V2])
async def test_final_export_cross_lesson_exact_duplicate_is_fresh_policy_only(monkeypatch, policy):
    from app.modules.ai.v3 import diversity_review, partitioned_extraction, service
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, V3Course
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext

    _, journal, client, _, _ = setup()
    corpus, rule = sample()
    corpus = replace(corpus, tenant_id=journal.tenant_id)
    context = OwnedSourceContext(corpus, journal, UUID(journal.tenant_id), journal.user_id, journal.job_id, ('d1',))
    lesson = V3Course.from_dict({'course_id': 'c', 'title': 't', 'lessons': [{'lesson_id': 'l1',
        'title': 't', 'module_title': 'm', 'content': 'Lesson', 'covered_rule_ids': ['r1'],
        'cases': [{'case_id': 'c1', 'rule_id': 'r1', 'learning_objective': 'x', 'variants': [{
            'variant_id': 'v1', 'scenario_premise': 'S', 'prompt': 'Original?',
            'correct_option': {'text': 'A'}, 'distractor_pool': [{'text': 'B'}, {'text': 'C'}, {'text': 'D'}],
            'source_quote': rule.source_quote}]}]}]}).lessons[0]
    repaired_variant = replace(lesson.cases[0].variants[0], prompt='Final duplicate?')
    first = replace(lesson, cases=(replace(lesson.cases[0], variants=(repaired_variant,)),))
    second = replace(first, lesson_id='l2', cases=(replace(first.cases[0], case_id='c2',
        variants=(replace(repaired_variant, variant_id='v2'),)),))
    groups = [CurriculumGroup('g1', 'topic', 's', (rule,)), CurriculumGroup('g2', 'topic', 's', (rule,))]
    async def extraction(*_args, **_kwargs):
        return DocumentRuleModel('t', 's', (rule,)), []
    monkeypatch.setattr(partitioned_extraction, 'extract_partitioned_rule_model', extraction)
    monkeypatch.setattr(service, '_build_curriculum_groups', lambda *_a, **_kw: groups)
    monkeypatch.setattr(service.V3GenerationPipeline, 'generate_lesson_with_scenarios',
                        AsyncMock(side_effect=[lesson, lesson]))
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_answer', AsyncMock(return_value={'verdict': 'COMPLETE', 'claims': []}))
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_lesson', AsyncMock(return_value={'verdict': 'NEEDS_REVISION'}))
    monkeypatch.setattr(service, '_bind_rendered_quote_candidates', lambda *_a: (first, []))
    # Generate distinct final lesson identities while preserving the repaired identical stem.
    calls = iter([first, second])
    monkeypatch.setattr(service, '_bind_rendered_quote_candidates', lambda *_a: (next(calls), []))
    monkeypatch.setattr(service, '_nonliteral_case_citation_ids', lambda *_a: ['v1'])
    monkeypatch.setattr(diversity_review, 'review_final_lesson', AsyncMock(return_value={'status': 'unknown'}))
    artifacts = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=client,
        extraction_journal=journal, route_fingerprint='b' * 64, direct_client=client,
        authenticated_qa_policy=policy, owned_source_context=context)
    exported = [q.question for assessment in artifacts.assessment.assessments for q in assessment.mcq]
    assert len(exported) == 2 and exported[0] == exported[1] and 'Final duplicate?' in exported[0]
    matching = [v for v in artifacts.diagnostics['violations'] if 'В разных уроках совпадают' in v]
    assert len(matching) == (1 if policy == DIRECT_POLICY else 0)
    assert all('Final duplicate?' not in item for item in matching)
