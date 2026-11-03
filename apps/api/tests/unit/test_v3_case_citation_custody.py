from types import SimpleNamespace

import pytest

from app.modules.ai.v3.service import _nonliteral_case_citation_ids, _unbound_case_citation_ids


def fixture(quote, *, text="Before required condition. After final action.", start=0, end=None):
    variant = SimpleNamespace(variant_id="v1", source_quote=quote)
    lesson = SimpleNamespace(cases=(SimpleNamespace(rule_id="r1", variants=(variant,)),))
    rule = SimpleNamespace(rule_id="r1", doc_id="d1", source_revision="rev1", source_start=start,
                           source_end=len(text) if end is None else end)
    document = SimpleNamespace(doc_id="d1", source_revision="rev1", source_text=text)
    return lesson, rule, SimpleNamespace(documents=(document,))


def test_contiguous_quote_with_whitespace_is_bound():
    lesson, rule, corpus = fixture("required   condition.")
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == []


def test_omitted_intervening_qualifier_remains_held_without_rewrite():
    quote = "Before After final action."
    lesson, rule, corpus = fixture(quote)
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]
    assert lesson.cases[0].variants[0].source_quote == quote


def test_wrong_rule_span_duplicate_rule_or_wrong_revision_fails_closed():
    lesson, rule, corpus = fixture("After final action.", end=20)
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]
    assert _unbound_case_citation_ids(lesson, [rule, rule], corpus) == ["v1"]
    corpus.documents[0].source_revision = "other"
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]


def test_empty_quote_or_missing_original_source_is_held():
    lesson, rule, corpus = fixture("")
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]
    lesson.cases[0].variants[0].source_quote = "required condition."
    corpus.documents[0].source_text = None
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]


def test_duplicate_same_rule_occurrence_is_ambiguous():
    lesson, rule, corpus = fixture("same requirement", text="same requirement; same requirement")
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]
    lesson, rule, corpus = fixture("aa", text="aaa")
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]


def test_early_stop_requires_known_literal_absence_not_merely_missing_context():
    lesson, rule, corpus = fixture("Before After final action.")
    assert _nonliteral_case_citation_ids(lesson, [rule], corpus) == ["v1"]
    corpus.documents[0].source_text = None
    assert _nonliteral_case_citation_ids(lesson, [rule], corpus) == []
    assert _unbound_case_citation_ids(lesson, [rule], corpus) == ["v1"]


def test_mixed_source_quote_outside_owned_rule_span_holds_early():
    source = "Owned rule text. Separate sibling rule text."
    lesson, rule, corpus = fixture("Separate sibling rule text.", text=source, end=len("Owned rule text."))
    assert _nonliteral_case_citation_ids(lesson, [rule], corpus) == ["v1"]


def test_early_stop_rejects_other_rule_quote_without_collapsing_unknown_ownership():
    from dataclasses import replace

    from app.modules.ai.v3.models import RuleEntity

    source = "First owner: close door. Second owner: open window."
    boundary = source.index("Second owner:")
    first = RuleEntity(rule_id="first", section="s", title="t", statement="s", doc_id="d1",
                       source_revision="rev1", source_start=0, source_end=boundary)
    second = replace(first, rule_id="second", source_start=boundary, source_end=len(source))
    variant = SimpleNamespace(variant_id="wrong-owner", source_quote="open window.")
    lesson = SimpleNamespace(cases=(SimpleNamespace(rule_id="first", variants=(variant,)),))
    corpus = SimpleNamespace(documents=(SimpleNamespace(doc_id="d1", source_revision="rev1", source_text=source),))
    assert _nonliteral_case_citation_ids(lesson, [first, second], corpus) == ["wrong-owner"]
    assert _unbound_case_citation_ids(lesson, [first, second], corpus) == ["wrong-owner"]
    variant.source_quote = "close door."
    assert _nonliteral_case_citation_ids(lesson, [first, second], corpus) == []
    assert _unbound_case_citation_ids(lesson, [first, second], corpus) == []
    variant.source_quote = "open window."
    assert _nonliteral_case_citation_ids(lesson, [first, first, second], corpus) == []
    assert _unbound_case_citation_ids(lesson, [first, first, second], corpus) == ["wrong-owner"]
    unknown = replace(first, source_start=None)
    assert _nonliteral_case_citation_ids(lesson, [unknown, second], corpus) == []
    assert _unbound_case_citation_ids(lesson, [unknown, second], corpus) == ["wrong-owner"]


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_backed,later_group", [(False, False), (True, False), (False, True)])
async def test_nonliteral_quote_stops_all_lesson_review_calls(monkeypatch, journal_backed, later_group):
    from dataclasses import replace

    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3 import service
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity, V3Course

    source = "First condition. Required intervening qualifier. Final action."
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="s", doc_id="d1",
                      source_revision="rev1", source_start=0, source_end=len(source), source_quote=source)
    group = CurriculumGroup(group_id="g1", display_title="t", section="s", primary_rules=(rule,))
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "s", "lessons": [{
        "lesson_id": "l1", "title": "t", "module_title": "t", "content": "Lesson.",
        "covered_rule_ids": ["r1"], "cases": [{"case_id": "case1", "rule_id": "r1", "learning_objective": "x",
        "variants": [{"variant_id": "v1", "prompt": "What?", "correct_option": {"text": "A"},
        "distractor_pool": [{"text": "B"}, {"text": "C"}, {"text": "D"}],
        "source_quote": "First condition. Final action."}]}]}]}).lessons[0]
    bad_case = lesson.cases[0]
    sibling = replace(bad_case.variants[0], variant_id="v2", source_quote="Final action.")
    lesson = replace(lesson, cases=(replace(bad_case, variants=(bad_case.variants[0], sibling)),))
    next_lesson = replace(lesson, lesson_id="l2", cases=(replace(bad_case, variants=(sibling,)),))
    document = DirectSourceDocument(doc_id="d1", title="t", filename="t.txt", category="general",
                                    source_revision="rev1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(document,), total_chars=len(source), total_chunks=0)
    async def extract(*_args, **_kwargs): return DocumentRuleModel(document_title="t", document_sha256="s", rules=(rule,))
    async def generate(*_args, **kwargs): return next_lesson if kwargs["lesson_theme"] == "later" else lesson
    review_messages = []
    async def forbid(messages, *_args, **_kwargs):
        review_messages.append(messages)
        return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5,
                "didactic_score": 5, "summary": "Independent review.", "defects": [],
                "claims": []}
    monkeypatch.setattr(service.V3GenerationPipeline, "extract_rule_model", extract)
    monkeypatch.setattr(service.V3GenerationPipeline, "generate_lesson_with_scenarios", generate)
    groups = [group, replace(group, group_id="g2", display_title="later")] if later_group else [group]
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_args, **_kwargs: groups)
    if journal_backed:
        from app.modules.ai.v3 import partitioned_extraction
        async def extract_partitioned(*_args, **_kwargs):
            return DocumentRuleModel(document_title="t", document_sha256="s", rules=(rule,)), []
        monkeypatch.setattr(partitioned_extraction, "extract_partitioned_rule_model", extract_partitioned)
    review_calls = []
    if later_group:
        async def review_later(_self, reviewed, *_args, **_kwargs):
            review_calls.append(reviewed.lesson_id)
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5,
                    "didactic_score": 5, "summary": "Sibling review.", "defects": []}
        monkeypatch.setattr(service.V3GenerationPipeline, "review_lesson", review_later)
    if journal_backed:
        from tests.unit.test_v3_partitioned_extraction import Journal as StageJournal
        options = {"extraction_journal": StageJournal(), "route_fingerprint": "a" * 64}
    else:
        options = {}
    artifacts = await service.generate_v3_course_from_corpus(corpus=corpus, intent=CourseIntent(), generation_client=forbid, **options)
    review = artifacts.diagnostics["validation_report"]["semantic_reviews"]["l1"]
    assert review["verdict"] == "NEEDS_REVISION"
    assert any("цитата не подтверждена целиком" in item for item in artifacts.diagnostics["violations"])
    assert artifacts.diagnostics["requires_source_review"] is True
    assert any("цитата не подтверждена целиком" in value for value in artifacts.diagnostics["violations"])
    assert len(artifacts.assessment.assessments[0].mcq) == 2
    assert review_calls == (["l1", "l2"] if later_group else [])


@pytest.mark.asyncio
async def test_real_stage_checkpoint_cold_replay_skips_held_review_and_advances(monkeypatch):
    import copy

    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3 import partitioned_extraction, service
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity

    source = "First condition. Required intervening qualifier. Final action."
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="s", doc_id="d1",
                      source_revision="rev1", source_start=0, source_end=len(source), source_quote=source)
    groups = [CurriculumGroup(group_id="g1", display_title="held-theme", section="s", primary_rules=(rule,)),
              CurriculumGroup(group_id="g2", display_title="later-theme", section="s", primary_rules=(rule,))]
    document = DirectSourceDocument(doc_id="d1", title="t", filename="t.txt", category="general",
                                    source_revision="rev1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(document,), total_chars=len(source), total_chunks=0)

    class Journal:
        tenant_id, job_id = "tenant", "job"
        def __init__(self, plans=None, values=None):
            self.plans, self.values = plans or {}, values or {}
        async def prepare(self, key, plan):
            assert key not in self.plans or self.plans[key] == plan
            self.plans[key] = copy.deepcopy(plan)
            return copy.deepcopy(self.values.get(key))
        async def save_value(self, key, value): self.values[key] = copy.deepcopy(value)
        async def read_owned_value(self, key, plan):
            return copy.deepcopy(self.values.get(key)) if self.plans.get(key) == plan else None

    async def extract(*_args, **_kwargs):
        return DocumentRuleModel(document_title="t", document_sha256="s", rules=(rule,)), []
    async def no_explanation_repair(lesson, *_args, **_kwargs): return lesson, False
    async def no_option_repair(lesson, *_args, **_kwargs): return lesson, False
    monkeypatch.setattr(partitioned_extraction, "extract_partitioned_rule_model", extract)
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_args, **_kwargs: groups)
    monkeypatch.setattr(service, "_repair_option_shortcuts", no_option_repair)
    from app.modules.ai.v3 import explanation_repair
    monkeypatch.setattr(explanation_repair, "repair_order_dependent_explanations", no_explanation_repair)
    calls = []
    async def fake_provider(messages, _response_format):
        text = str(messages)
        if "held-theme" in text or "later-theme" in text:
            held = "held-theme" in text
            calls.append("held-lesson" if held else "later-lesson")
            cases = [{"case_id": "case1", "rule_id": "r1", "learning_objective": "x", "variants": [{
                "variant_id": "v1", "prompt": "What?", "correct_option": {"text": "A"},
                "distractor_pool": [{"text": "B"}, {"text": "C"}, {"text": "D"}],
                "source_quote": "First condition. Final action."}]}] if held else []
            return {"lesson_id": "l1" if held else "l2", "title": "held" if held else "later",
                    "module_title": "t", "content": "Lesson.", "cases": cases}
        calls.append("later-review")
        return {"verdict": "NEEDS_REVISION", "factual_score": 1, "alignment_score": 1,
                "didactic_score": 1, "summary": "Review required", "defects": []}

    journal = Journal()
    first = await service.generate_v3_course_from_corpus(corpus=corpus, intent=CourseIntent(),
        generation_client=fake_provider, extraction_journal=journal, route_fingerprint="a" * 64)
    stage_plans = [p for key, p in journal.plans.items() if key.startswith("v3-stage-result:")]
    assert any(p["group_id"] == "g1" and p["stage"] == "lesson" for p in stage_plans)
    # The held lesson skips case/question review, but independent prose review
    # remains allowed and is checkpointed; the hold must not hide lesson claims.
    assert any(p["group_id"] == "g1" and p["stage"] == "review" for p in stage_plans)
    assert any(p["group_id"] == "g2" and p["stage"] == "review" for p in stage_plans)
    assert first.diagnostics["validation_report"]["semantic_reviews"]["l1"]["verdict"] == "NEEDS_REVISION"
    before = list(calls)
    cold = Journal(copy.deepcopy(journal.plans), copy.deepcopy(journal.values))
    second = await service.generate_v3_course_from_corpus(corpus=corpus, intent=CourseIntent(),
        generation_client=fake_provider, extraction_journal=cold, route_fingerprint="a" * 64)
    assert calls == before
    assert second.diagnostics["validation_report"]["semantic_reviews"]["l1"]["verdict"] == "NEEDS_REVISION"


@pytest.mark.asyncio
async def test_all_held_case_lesson_does_not_fallback_to_compatibility_questions(monkeypatch):
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3 import service
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity, V3Course

    source = "Owned rule text."
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="s", doc_id="d1",
                      source_revision="rev1", source_start=0, source_end=len(source), source_quote=source)
    group = CurriculumGroup(group_id="g1", display_title="held", section="s", primary_rules=(rule,))
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "s", "lessons": [{
        "lesson_id": "l1", "title": "t", "module_title": "t", "content": "Lesson prose.",
        "covered_rule_ids": ["r1"], "cases": [{"case_id": "c1", "rule_id": "r1", "learning_objective": "x",
        "variants": [{"variant_id": "v1", "prompt": "Q", "correct_option": {"text": "A"},
        "distractor_pool": [{"text": "B"}, {"text": "C"}, {"text": "D"}],
        "source_quote": "Missing quote."}]}],
        "questions": [{"question_id": "legacy", "scenario_premise": "S", "prompt": "Q",
        "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False},
                    {"text": "C", "is_correct": False}, {"text": "D", "is_correct": False}],
        "explanation": "E", "rule_id": "r1", "source_quote": source}]}]}).lessons[0]
    document = DirectSourceDocument(doc_id="d1", title="t", filename="t", category="general",
                                    source_revision="rev1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(document,), total_chars=len(source), total_chunks=0)
    async def extract(*_args, **_kwargs): return DocumentRuleModel(document_title="t", document_sha256="s", rules=(rule,))
    async def generate(*_args, **_kwargs): return lesson
    async def forbid_question(*_args, **_kwargs): raise AssertionError("held compatibility question was reviewed")
    async def prose_review(*_args, **_kwargs): return {"verdict": "SUPPORTED", "claims": [], "summary": "ok"}
    monkeypatch.setattr(service.V3GenerationPipeline, "extract_rule_model", extract)
    monkeypatch.setattr(service.V3GenerationPipeline, "generate_lesson_with_scenarios", generate)
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_args, **_kwargs: [group])
    monkeypatch.setattr(service.V3GenerationPipeline, "review_lesson", forbid_question)
    monkeypatch.setattr(service.V3GenerationPipeline, "review_question_options", forbid_question)
    monkeypatch.setattr(service.V3GenerationPipeline, "review_answer", prose_review)
    artifacts = await service.generate_v3_course_from_corpus(corpus=corpus, intent=CourseIntent(),
        generation_client=forbid_question)
    report = artifacts.diagnostics["validation_report"]["semantic_reviews"]["l1"]
    assert report["verdict"] == "NEEDS_REVISION"
    assert any("цитата не подтверждена целиком" in item for item in artifacts.diagnostics["violations"])


@pytest.mark.asyncio
async def test_repaired_valid_sibling_is_cited_while_held_sibling_stays_blocked(monkeypatch):
    from dataclasses import replace

    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3 import case_repair_gate, citation_expansion, option_repair, service
    from app.modules.ai.v3 import citation_review as citation_review_module
    from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity, V3Course
    from tests.unit.test_v3_partitioned_extraction import Journal

    source = "Owned rule text. Sibling rule text."
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="s", doc_id="d1",
                      source_revision="rev1", source_start=0, source_end=len(source), source_quote=source)
    group = CurriculumGroup(group_id="g1", display_title="mixed", section="s", primary_rules=(rule,))
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "s", "lessons": [{
        "lesson_id": "l1", "title": "t", "module_title": "t", "content": "Lesson prose.",
        "covered_rule_ids": ["r1"], "cases": [{"case_id": "c1", "rule_id": "r1", "learning_objective": "x",
        "variants": [
            {"variant_id": "sibling", "prompt": "Q2", "correct_option": {"text": "A2"},
                 "distractor_pool": [{"text": "B2"}, {"text": "C2"}, {"text": "D2"}],
                     "explanation": "Sibling explanation.", "source_quote": "Sibling rule text"},
            {"variant_id": "held", "prompt": "Q1", "correct_option": {"text": "A"},
             "distractor_pool": [{"text": "B"}, {"text": "C"}, {"text": "D"}], "source_quote": "Missing quote."}
        ]}]}]}).lessons[0]
    held_before = next(variant for variant in lesson.cases[0].variants if variant.variant_id == "held").to_dict()
    lesson = replace(lesson, questions=(lesson.cases[0].variants[0].assemble_question(seed=42),))
    document = DirectSourceDocument(doc_id="d1", title="t", filename="t", category="general",
                                    source_revision="rev1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(document,), total_chars=len(source), total_chunks=0)
    async def extract(*_args, **_kwargs): return DocumentRuleModel(document_title="t", document_sha256="s", rules=(rule,))
    async def generate(*_args, **_kwargs): return lesson
    review_count = 0
    async def review_lesson(_self, *_args, **_kwargs):
        nonlocal review_count
        review_count += 1
        return {"verdict": "NEEDS_REVISION" if review_count == 1 else "PASS", "factual_score": 4,
                "alignment_score": 4, "didactic_score": 4, "summary": "The repaired sibling remains source-grounded.", "defects": []}
    repair_inputs = []
    staged_scopes = []
    feedback_calls = []
    exported_courses = []
    async def repair_case(current, *_args, **_kwargs):
        repair_inputs.append(current)
        case = current.cases[0]
        sibling = next(variant for variant in case.variants if variant.variant_id == "sibling")
        sibling = replace(sibling, correct_option=replace(sibling.correct_option, text="A2 repaired"),
                          explanation="Repaired explanation.", source_quote="Sibling rule text.")
        return replace(current, cases=(replace(case, variants=(sibling,)),)), True
    async def option_review(*_args, **_kwargs):
        return {"options": [
            {"index": 0, "verdict": "SUPPORTED", "claims": [{"claim": "correct", "status": "SUPPORTED", "reason": "source"}],
             "summary": "supported", "omitted_required_elements": []},
            {"index": 1, "verdict": "SUPPORTED", "claims": [{"claim": "wrong", "status": "SUPPORTED", "reason": "source"}],
             "summary": "incorrectly supported", "omitted_required_elements": []},
            {"index": 2, "verdict": "CONTRADICTED", "claims": [{"claim": "wrong", "status": "CONTRADICTED", "reason": "source"}],
             "summary": "contradicted", "omitted_required_elements": []},
            {"index": 3, "verdict": "CONTRADICTED", "claims": [{"claim": "wrong", "status": "CONTRADICTED", "reason": "source"}],
             "summary": "contradicted", "omitted_required_elements": []},
        ]}
    async def completeness_review(*_args, **_kwargs):
        return {"answers": [{"index": 0, "omissions": []}]}
    async def generation(messages, *_args, **_kwargs):
        if "Карту регламента" in messages[0]["content"]:
            return {"rules": [{"rule_id": "r1", "section": "s", "title": "t",
                               "statement": source, "source_quote": source}]}
        return await option_review(messages)
    citation_payloads = []
    citation_review_calls = 0
    async def citation_review(items, *_args, **_kwargs):
        nonlocal citation_review_calls
        citation_review_calls += 1
        citation_payloads.extend(items)
        verdict = "PARTIAL" if citation_review_calls == 1 else "COMPLETE"
        return {item["id"]: {"id": item["id"], "summary": "supported",
                              "unsupported": (["needs full rule context"] if verdict == "PARTIAL" else []),
                              "verdict": verdict}
                for item in items}
    fingerprints = []
    fingerprint_inputs = []
    original_fingerprint = citation_expansion.citation_question_fingerprint
    def capture_fingerprint(*args, **kwargs):
        value = original_fingerprint(*args, **kwargs)
        if value:
            fingerprints.append(value)
            fingerprint_inputs.append((args[0], args[1], value))
        return value
    monkeypatch.setattr(citation_expansion, "citation_question_fingerprint", capture_fingerprint)
    monkeypatch.setattr(service.V3GenerationPipeline, "extract_rule_model", extract)
    monkeypatch.setattr(service.V3GenerationPipeline, "generate_lesson_with_scenarios", generate)
    monkeypatch.setattr(service, "_build_curriculum_groups", lambda *_args, **_kwargs: [group])
    monkeypatch.setattr(service.V3GenerationPipeline, "review_lesson", review_lesson)
    monkeypatch.setattr(service.V3GenerationPipeline, "review_question_options", option_review)
    monkeypatch.setattr(service.V3GenerationPipeline, "review_question_compatibility", option_review)
    monkeypatch.setattr(service.V3GenerationPipeline, "review_answer_completeness", completeness_review)
    original_adapter = service.v3_course_to_generation_artifacts
    def capture_export(course, *args, **kwargs):
        exported_courses.append(course)
        return original_adapter(course, *args, **kwargs)
    monkeypatch.setattr(service, "v3_course_to_generation_artifacts", capture_export)
    monkeypatch.setattr(service, "_repair_reviewed_case", repair_case)
    async def distractor_feedback_spy(*_args, **_kwargs):
        feedback_calls.append(True)
        raise AssertionError("mixed held case must not enter distractor feedback repair")
    monkeypatch.setattr(option_repair, "repair_distractor_feedback", distractor_feedback_spy)
    original_stage = case_repair_gate.review_staged_case
    async def stage_spy(candidate, *args, **kwargs):
        staged_scopes.append((candidate, args[9] if len(args) > 9 else None))
        return await original_stage(candidate, *args, **kwargs)
    monkeypatch.setattr(case_repair_gate, "review_staged_case", stage_spy)
    monkeypatch.setattr(citation_review_module, "review_displayed_citations", citation_review)
    journal = Journal()
    journal.tenant_id = "tenant"
    artifacts = await service.generate_v3_course_from_corpus(corpus=corpus, intent=CourseIntent(),
        generation_client=generation, extraction_journal=journal, route_fingerprint="a" * 64)
    report = artifacts.diagnostics["validation_report"]["semantic_reviews"]["l1"]
    repairs = artifacts.diagnostics["validation_report"]["semantic_repairs"]
    assert report["verdict"] == "NEEDS_REVISION"
    assert any("held" in value for value in artifacts.diagnostics["violations"])
    assert not [row for row in repairs if row.get("accepted") is True]
    feedback_attempts = [row for row in report["answer_checks"] if row.get("distractor_repair")]
    assert feedback_attempts and feedback_attempts[0]["distractor_repair"]["rejected"] == "case_contains_held_variant"
    assert len(repair_inputs) == 0
    assert feedback_calls == []
    assert len(staged_scopes) == 0
    assert len(exported_courses) == 1
    exported_lesson = exported_courses[0].lessons[0]
    assert next(variant for variant in exported_lesson.cases[0].variants if variant.variant_id == "held").to_dict() == held_before
    assert exported_lesson.questions[0].source_quote == source
    assert len(citation_payloads) == 2
    payload = citation_payloads[0]
    assert payload["id"] == "sibling-assembled"
    assert payload["answer"] == "A2"
    assert payload["explanation"] == "Sibling explanation."
    assert payload["displayed_quote"] == "Sibling rule text"
    assert citation_payloads[1]["displayed_quote"] == source
    assert payload["source_identity"]
    assert fingerprints
    final_fingerprints = [value for lesson_value, question_id, value in fingerprint_inputs
                          if question_id == "sibling-assembled" and any(
                              variant.variant_id == "sibling" and variant.source_quote == payload["displayed_quote"]
                              for case in lesson_value.cases for variant in case.variants)]
    assert final_fingerprints
    assert final_fingerprints[-1] == original_fingerprint(
        next(lesson_value for lesson_value, question_id, value in fingerprint_inputs
             if question_id == "sibling-assembled" and value == final_fingerprints[-1]),
        "sibling-assembled",
    )
    assert all("held-assembled" not in row["question_id"] for row in report["citation_checks"])
    assert {row["question_id"] for row in report["citation_checks"]} == {"sibling-assembled"}
    assert report["citation_checks"][0]["candidate_accepted"] is True
    final_full_fingerprints = [value for lesson_value, question_id, value in fingerprint_inputs
                               if question_id == "sibling-assembled" and any(
                                   variant.variant_id == "sibling" and variant.source_quote == source
                                   for case in lesson_value.cases for variant in case.variants)]
    assert final_full_fingerprints
    assert report["citation_checks"][0]["candidate_fingerprint"] == final_full_fingerprints[-1]
    assert report["citation_checks"][0]["candidate_fingerprint"] == original_fingerprint(
        exported_lesson, "sibling-assembled"
    )
