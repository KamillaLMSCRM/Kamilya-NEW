"""Confirmed source references must remain tenant, revision and span bound."""

import hashlib
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity
from app.modules.ai.v3.service import _build_curriculum_groups, generate_v3_course_from_corpus
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision, reference_context_for_rules


def setup_decision():
    source = "Порядок: см. п. 2.\n2. Подписать билет и внести отметку."
    ref = "см. п. 2"
    target = "Подписать билет и внести отметку."
    doc = DirectSourceDocument(doc_id="doc-1", title="d", filename="d", category="general",
                               source_revision="rev-1", chunks=(), source_text=source)
    a, b = source.index(ref), source.index(target)
    decision = SourceReferenceDecision(tenant_id="tenant-1", document_id="doc-1", source_revision="rev-1",
        converted_text_sha256=hashlib.sha256(source.encode()).hexdigest(), reference_start=a, reference_end=a+len(ref),
        reference_exact=ref, target_start=b, target_end=b+len(target), target_exact=target, authority="owner_chat")
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="Порядок: см. п. 2",
                      doc_id="doc-1", source_revision="rev-1", source_start=0, source_end=len(source))
    return doc, decision, rule


def test_confirmed_reference_is_scoped_to_exact_source_and_rule():
    doc, decision, rule = setup_decision()
    context = reference_context_for_rules("tenant-1", (doc,), (decision,), (rule,))
    assert len(context) == 1 and "Подписать билет и внести отметку." in context[0]
    assert reference_context_for_rules("tenant-1", (doc,), (decision,), (replace(rule, source_start=0, source_end=4),)) == ()


def test_confirmed_reference_links_exact_unique_source_quotes_not_shared_unit():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.")
    target = replace(referring, rule_id="target", section="target", statement="Подписать билет",
                     source_quote=decision.target_exact)
    unrelated = replace(referring, rule_id="unrelated", section="other", statement="Другое",
                        source_quote="Порядок:")
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                              rules=(referring, target, unrelated))
    before = next(group for group in _build_curriculum_groups(model) if referring in group.primary_rules)
    assert any("пункт '2'" in issue for issue in before.unresolved_dependencies)
    after = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert not after.unresolved_dependencies
    assert target in after.context_prerequisite_rules
    assert unrelated not in after.context_prerequisite_rules


def test_confirmed_reference_does_not_resolve_multiple_model_occurrences():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.",
                        statement="См. п. 2 и затем снова п. 2")
    target = replace(referring, rule_id="target", section="target", statement="Подписать билет",
                     source_quote=decision.target_exact)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=(referring, target))
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)
    assert target in group.context_prerequisite_rules


@pytest.mark.parametrize("field", ["conditions", "exceptions", "timing", "consequences"])
def test_confirmed_reference_does_not_resolve_occurrences_in_distinct_fields(field):
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    second = ("См. п. 2",) if field in ("conditions", "exceptions") else "См. п. 2"
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.", **{field: second})
    target = replace(referring, rule_id="target", section="target", statement="Подписать билет",
                     conditions=(), exceptions=(), timing="", consequences="", source_quote=decision.target_exact)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=(referring, target))
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)
    assert target in group.context_prerequisite_rules


def test_confirmed_reference_keeps_ambiguity_with_duplicate_target_rules():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.")
    target = replace(referring, rule_id="target1", section="target", statement="Подписать билет",
                     source_quote=decision.target_exact)
    duplicate = replace(target, rule_id="target2")
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                              rules=(referring, target, duplicate))
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)
    assert not group.context_prerequisite_rules


def test_unique_numbered_target_does_not_validate_repeated_model_references():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.",
                        timing="Другая непроверенная ссылка: п. 2")
    target = replace(referring, rule_id="target", title="пункт 2", section="target", timing="",
                     statement="Подписать билет", source_quote=decision.target_exact)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=(referring, target))
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert target in group.context_prerequisite_rules
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)


def test_duplicate_source_targets_cannot_be_resolved_by_unique_numbered_candidate():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.", timing="См. п. 2")
    target = replace(referring, rule_id="target", section="target", title="пункт 2", timing="",
                     statement="Подписать билет", source_quote=decision.target_exact)
    duplicate = replace(target, rule_id="other", title="Другое")
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=(referring, target, duplicate))
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)


def test_single_compound_reference_does_not_inherit_standalone_owner_decision():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.",
                        statement="См. пункт 2 раздела 9")
    target = replace(referring, rule_id="target", section="target", title="пункт 2", statement="Подписать билет",
                     source_quote=decision.target_exact)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=(referring, target))
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert target in group.context_prerequisite_rules
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)


@pytest.mark.parametrize("duplicate_target", [False, True])
def test_missing_model_reference_cannot_hide_unbound_source_dependency(duplicate_target):
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.", statement="Порядок действий")
    target = replace(referring, rule_id="target", section="target", title="пункт 2", statement="Подписать билет",
                     source_quote=decision.target_exact)
    rules = (referring, target, replace(target, rule_id="other")) if duplicate_target else (referring,)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=rules)
    group = next(group for group in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                 if referring in group.primary_rules)
    assert any("пункт '2'" in issue for issue in group.unresolved_dependencies)


def test_competing_decisions_cannot_hide_source_dependency():
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.", statement="Порядок действий")
    target = replace(referring, rule_id="target", section="target", title="target", statement="Подписать билет",
                     source_quote=decision.target_exact)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=(referring, target))
    with pytest.raises(ValueError, match="reference_decision_duplicate"):
        _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision, decision))


@pytest.mark.parametrize("duplicate_referrer", [False, True])
def test_confirmed_source_occurrence_without_unique_rule_stays_visible(duplicate_referrer):
    doc, decision, referring = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    referring = replace(referring, section="ref", statement="Порядок действий",
                        source_quote="Порядок: см. п. 2." if duplicate_referrer else "Порядок:")
    target = replace(referring, rule_id="target", section="target", statement="Подписать билет",
                     source_quote=decision.target_exact)
    rules = (referring, target, replace(referring, rule_id="other")) if duplicate_referrer else (referring, target)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=rules)
    from app.modules.ai.v3.reference_coverage import unmatched_confirmed_references
    unmatched = unmatched_confirmed_references(corpus, list(rules), (decision,))
    assert len(unmatched) == 1 and len(unmatched[0]) == 64 and "см. п. 2" not in unmatched[0]
    groups = _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
    assert any("подтвержденная ссылка" in issue.casefold() for group in groups
               for issue in group.unresolved_dependencies)
    assert all(decision.reference_exact not in issue for group in groups for issue in group.unresolved_dependencies)


def test_confirmed_reference_without_any_extracted_rule_fails_closed():
    doc, decision, _ = setup_decision()
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(doc.source_text or ""), total_chunks=0)
    model = DocumentRuleModel(document_title="d", document_sha256="a" * 64, rules=())
    with pytest.raises(ValueError, match="v3_confirmed_reference_without_extracted_rule"):
        _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))


@pytest.mark.parametrize("change", ["tenant", "revision", "content", "target", "authority"])
def test_foreign_stale_or_untrusted_reference_fails_closed(change):
    doc, decision, rule = setup_decision()
    if change == "tenant":
        decision = replace(decision, tenant_id="other")
    elif change == "revision":
        decision = replace(decision, source_revision="old")
    elif change == "content":
        doc = replace(doc, source_text=doc.source_text + " изменено")
    elif change == "target":
        decision = replace(decision, target_exact="выдуманное правило")
    else:
        decision = replace(decision, authority="model")
    with pytest.raises(ValueError, match="reference_decision_"):
        reference_context_for_rules("tenant-1", (doc,), (decision,), (rule,))


@pytest.mark.asyncio
async def test_trusted_decision_reaches_only_matching_lesson_without_becoming_a_quote():
    doc, decision, _ = setup_decision()
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(doc.source_text or ""), total_chunks=0)

    class Journal:
        tenant_id = "tenant-1"
        job_id = "job-1"

        def __init__(self):
            self.plans = {}
            self.values = {}

        async def prepare(self, key, plan):
            self.plans[key] = plan
            return self.values.get(key)

        async def save_value(self, key, value):
            self.values[key] = value

        async def read_owned_value(self, key, expected_plan):
            return self.values.get(key) if self.plans.get(key) == expected_plan else None

    requests = []
    reviews = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            return {"rules": [{"rule_id": "r1", "statement": "См. п. 2", "source_quote": decision.reference_exact}]}
        if "независимый контролер" in system:
            reviews.append(messages[1]["content"])
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": []}
        requests.append(messages[1]["content"])
        return {"lesson_id": "l1", "title": "Урок", "content": "Материал", "cases": []}

    journal = Journal()
    result = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=invoke,
        extraction_journal=journal, route_fingerprint="a" * 64, reference_decisions=(decision,))
    assert len(requests) == 1
    assert decision.reference_exact in requests[0] and decision.target_exact in requests[0]
    assert "не выдавай уточнение за цитату" in requests[0]
    assert decision.target_exact in reviews[0] and "НЕ ЦИТАТЫ ИСТОЧНИКА" in reviews[0]
    assert any("уточнения ссылок" in warning for warning in result.content.source_warnings)
    assert result.diagnostics["requires_source_review"]
    await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=invoke,
        extraction_journal=journal, route_fingerprint="a" * 64)
    assert len(requests) == 2 and "ПРОВЕРЕННЫЕ УТОЧНЕНИЯ" not in requests[1]
    assert len(reviews) == 2 and "УТОЧНЕНИЯ ССЫЛОК, НЕ ЦИТАТЫ" not in reviews[1]
