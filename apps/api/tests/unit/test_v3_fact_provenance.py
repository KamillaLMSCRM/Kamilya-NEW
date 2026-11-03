"""Offline source-fact reconstruction and unsupported-location checks."""
import socket
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument, direct_source_chunks
from app.modules.ai.evidence_engine.application import _locator_values, build_evidence_source
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.fact_provenance import exact_narrative_fact_references
from app.modules.ai.v3.models import RuleEntity, V3Course, V3Lesson


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(httpx, "Client", blocked)
    monkeypatch.setattr(httpx, "AsyncClient", blocked)


def source(text, doc_id=None):
    doc_id, revision = str(doc_id or uuid4()), "document:" + "a" * 64
    chunks = direct_source_chunks(text, document_id=doc_id, filename="source.md", title="Synthetic", source_revision=revision)
    doc = DirectSourceDocument(doc_id=doc_id, title="Synthetic", filename="source.md", category="general",
                               source_revision=revision, chunks=chunks, source_text=text)
    return DirectSourceCorpus(tenant_id="tenant", documents=(doc,), total_chars=len(text), total_chunks=len(chunks))


def rule_for(corpus, fact):
    doc = corpus.documents[0]
    start = doc.source_text.index(fact.value)
    return RuleEntity("r", "s", "title", fact.value, source_quote=fact.value, doc_id=doc.doc_id,
                      source_revision=doc.source_revision, source_start=start, source_end=start + len(fact.value))


def test_narrative_facts_reconstruct_with_exact_correction_identity():
    corpus = source("# Procedure\n\nCheck every document before approval.")
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in corpus.documents[0].source_text)
    refs = exact_narrative_fact_references(corpus, (rule_for(corpus, fact),))
    assert refs and refs[0]["fact_id"] == fact.fact_id and refs[0]["source_locator"] == fact.source_locator
    doc = corpus.documents[0]
    rebuilt_doc = replace(doc, chunks=direct_source_chunks(doc.source_text, document_id=doc.doc_id,
        filename=doc.filename, title=doc.title, source_revision=doc.source_revision))
    reconstructed = {f.fact_id: f for f in build_evidence_source(replace(corpus, documents=(rebuilt_doc,))).generation_facts}
    assert reconstructed[refs[0]["fact_id"]].source_locator == refs[0]["source_locator"]
    assert _locator_values(refs[0]["source_locator"])["source_revision"] == corpus.documents[0].source_revision


def test_table_and_stale_or_ambiguous_locations_are_held():
    corpus = source("# [Worksheet] Items\n\n| Field | A | B |\n| --- | --- | --- |\n| Warranty | 24 | 18 |")
    fact = next(f for f in build_evidence_source(corpus).generation_facts if _locator_values(f.source_locator).get("row") and f.value == "24")
    assert exact_narrative_fact_references(corpus, (rule_for(corpus, fact),)) is None
    corpus = source("# Procedure\n\nCheck every document before approval.")
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in corpus.documents[0].source_text)
    rule = rule_for(corpus, fact)
    assert exact_narrative_fact_references(corpus, (replace(rule, source_revision="stale"),)) is None
    doc = corpus.documents[0]
    assert exact_narrative_fact_references(replace(corpus, documents=(replace(doc, source_text=doc.source_text + " changed"),)), (rule,)) is None
    assert exact_narrative_fact_references(corpus, (rule, rule)) is None


def test_adapter_emits_correction_identity_only_for_exact_owned_narrative():
    corpus = source("# Procedure\n\nCheck every document before approval.")
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in corpus.documents[0].source_text)
    rule = rule_for(corpus, fact)
    lesson = V3Lesson("l", "title", "module", "lesson", (rule.rule_id,))
    course = V3Course("c", "title", "a" * 64, (lesson,))
    kwargs = dict(source_corpus=corpus, source_rules=(rule,), exact_narrative_facts=True)
    output = v3_course_to_generation_artifacts(course, **kwargs)
    mapped = output.content.modules[0].lessons[0]
    assert mapped.source_references[0]["fact_id"] == fact.fact_id
    assert mapped.source_references[0]["source_locator"] == fact.source_locator
    assert mapped.source_validation_status == "needs_review"
    bad = v3_course_to_generation_artifacts(course, **(kwargs | {"source_rules": (replace(rule, source_revision="stale"),)}))
    assert bad.content.modules[0].lessons[0].source_references == []
    assert bad.diagnostics["requires_source_review"] is True


@pytest.mark.asyncio
async def test_adapter_references_resolve_in_correction_workbench(monkeypatch):
    from app.modules.methodologist_workbench import correction_context
    from tests.unit.test_correction_context import DOCUMENT, LESSON, TENANT, _actor, _patch

    corpus = replace(source("# Procedure\n\nCheck every document before approval.", DOCUMENT), tenant_id=str(TENANT))
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in corpus.documents[0].source_text)
    rule = rule_for(corpus, fact)
    lesson = V3Lesson("l", "title", "module", "lesson", (rule.rule_id,))
    course = V3Course("c", "title", "a" * 64, (lesson,))
    output = v3_course_to_generation_artifacts(course, source_corpus=corpus, source_rules=(rule,),
                                               exact_narrative_facts=True)
    refs = output.content.modules[0].lessons[0].source_references
    db, persisted, *_ = _patch(monkeypatch)
    persisted.source_references = refs
    async def rebuild(*_args, **_kwargs):
        return corpus
    monkeypatch.setattr(correction_context, "build_direct_source_corpus", rebuild)
    monkeypatch.setattr(correction_context, "build_evidence_source", build_evidence_source)
    resolved = await correction_context.resolve_lesson_correction(db, _actor(), LESSON)
    assert resolved.excerpts[0].citation.locator == "fact:" + fact.fact_id


def test_rechunked_duplicate_quote_and_foreign_document_do_not_map():
    corpus = source("# Procedure\n\nCheck every document before approval.")
    doc = corpus.documents[0]
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in doc.source_text)
    rule = rule_for(corpus, fact)
    repeated = doc.source_text + "\n\n" + fact.value
    updated = replace(doc, source_text=repeated, chunks=direct_source_chunks(repeated, document_id=doc.doc_id,
        filename=doc.filename, title=doc.title, source_revision=doc.source_revision))
    assert exact_narrative_fact_references(replace(corpus, documents=(updated,)), (rule,)) is None
    foreign = source("# Other\n\nDifferent rule.").documents[0]
    multi = replace(corpus, documents=(doc, foreign))
    assert exact_narrative_fact_references(multi, (replace(rule, doc_id=foreign.doc_id),)) is None


def test_unexpected_reconstruction_failure_fails_closed_once(monkeypatch):
    from app.modules.ai.v3 import fact_provenance
    corpus = source("# Procedure\n\nCheck every document before approval.")
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in corpus.documents[0].source_text)
    rule = rule_for(corpus, fact)
    calls = []
    def broken(_corpus):
        calls.append(1)
        raise RuntimeError("synthetic reconstruction failure")
    monkeypatch.setattr(fact_provenance, "build_evidence_source", broken)
    assert exact_narrative_fact_references(corpus, (rule,)) is None
    assert calls == [1]
    def broken_chunks(*_args, **_kwargs):
        raise RuntimeError("synthetic chunk failure")
    monkeypatch.setattr(fact_provenance, "direct_source_chunks", broken_chunks)
    assert exact_narrative_fact_references(corpus, (rule,)) is None
    assert calls == [1]


def test_unique_quote_subspan_maps_to_one_enclosing_fact_without_semantic_approval():
    corpus = source("# Procedure\n\nCheck every document before approval.")
    doc = corpus.documents[0]
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in doc.source_text)
    rule = replace(rule_for(corpus, fact), source_quote="document before")
    refs = exact_narrative_fact_references(corpus, (rule,))
    assert refs and refs[0]["fact_id"] == fact.fact_id and refs[0]["source_locator"] == fact.source_locator
    assert fact.value != rule.source_quote


def test_subspan_fact_crossing_authorized_rule_unit_is_held():
    corpus = source("# Procedure\n\nCheck every document before approval.")
    doc = corpus.documents[0]
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in doc.source_text)
    quote = "document before"
    start = doc.source_text.index(quote)
    rule = replace(rule_for(corpus, fact), source_quote=quote, source_start=start, source_end=start + len(quote))
    assert exact_narrative_fact_references(corpus, (rule,)) is None


def test_ambiguous_enclosing_facts_and_uncertainty_are_held(monkeypatch):
    from types import SimpleNamespace

    from app.modules.ai.v3 import fact_provenance

    corpus = source("# Procedure\n\nCheck every document before approval.")
    doc = corpus.documents[0]
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in doc.source_text)
    rule = replace(rule_for(corpus, fact), source_quote="document")
    one = replace(fact, fact_id="one", value="Check every document")
    two = replace(fact, fact_id="two", value="document before approval.")
    monkeypatch.setattr(fact_provenance, "build_evidence_source", lambda _: SimpleNamespace(generation_facts=(one, two)))
    assert exact_narrative_fact_references(corpus, (rule,)) is None
    monkeypatch.setattr(fact_provenance, "build_evidence_source", lambda _: SimpleNamespace(generation_facts=(replace(one, uncertainty="unknown"),)))
    assert exact_narrative_fact_references(corpus, (rule,)) is None


def test_duplicate_enclosing_text_rechunked_holds():
    corpus = source("# Procedure\n\nCheck every document before approval.")
    doc = corpus.documents[0]
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in doc.source_text)
    rule = replace(rule_for(corpus, fact), source_quote="document before")
    text = doc.source_text + "\n\n" + fact.value
    changed = replace(doc, source_text=text, chunks=direct_source_chunks(text, document_id=doc.doc_id,
        filename=doc.filename, title=doc.title, source_revision=doc.source_revision))
    assert exact_narrative_fact_references(replace(corpus, documents=(changed,)), (rule,)) is None


@pytest.mark.asyncio
async def test_subspan_reference_reconstructs_in_correction_workbench(monkeypatch):
    from app.modules.methodologist_workbench import correction_context
    from tests.unit.test_correction_context import DOCUMENT, LESSON, TENANT, _actor, _patch

    corpus = replace(source("# Procedure\n\nCheck every document before approval.", DOCUMENT), tenant_id=str(TENANT))
    fact = next(f for f in build_evidence_source(corpus).generation_facts if f.value in corpus.documents[0].source_text)
    rule = replace(rule_for(corpus, fact), source_quote="document before")
    refs = exact_narrative_fact_references(corpus, (rule,))
    assert refs and refs[0]["fact_id"] == fact.fact_id
    db, persisted, *_ = _patch(monkeypatch)
    persisted.source_references = refs
    async def rebuild(*_args, **_kwargs):
        return corpus
    monkeypatch.setattr(correction_context, "build_direct_source_corpus", rebuild)
    monkeypatch.setattr(correction_context, "build_evidence_source", build_evidence_source)
    resolved = await correction_context.resolve_lesson_correction(db, _actor(), LESSON)
    assert resolved.excerpts[0].citation.locator == "fact:" + fact.fact_id
