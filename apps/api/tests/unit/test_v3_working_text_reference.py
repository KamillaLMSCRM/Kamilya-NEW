"""Offline exact working-text span and correction revalidation."""
import socket
from dataclasses import replace

import httpx
import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.models import RuleEntity, V3Course, V3Lesson
from app.modules.ai.v3.working_text_reference import working_text_references
from app.modules.methodologist_workbench import correction_context
from app.modules.methodologist_workbench.correction_contract import CorrectionError
from tests.unit.test_correction_context import DOCUMENT, LESSON, TENANT, _actor, _patch


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs): raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(httpx, "Client", blocked)
    monkeypatch.setattr(httpx, "AsyncClient", blocked)


def setup_span():
    text = "Заголовок 🐈\nПроверить документ до согласования."
    doc = DirectSourceDocument(doc_id=str(DOCUMENT), title="t", filename="t", category="general",
        source_revision="document:" + "a" * 64, chunks=(), source_text=text)
    corpus = DirectSourceCorpus(tenant_id=str(TENANT), documents=(doc,), total_chars=len(text), total_chunks=0)
    quote = "Проверить документ до согласования."
    rule = RuleEntity("r", "s", "t", quote, source_quote=quote, doc_id=str(DOCUMENT),
        source_revision=doc.source_revision, source_start=text.index(quote), source_end=len(text))
    return corpus, rule


@pytest.mark.asyncio
async def test_span_resolves_in_actual_correction_context_and_rejects_stale(monkeypatch):
    corpus, rule = setup_span()
    refs = working_text_references(corpus, (rule,))
    assert refs and "Проверить" not in str(refs)
    db, lesson, *_ = _patch(monkeypatch)
    lesson.source_references = refs
    async def rebuild(*_args, **_kwargs): return corpus
    monkeypatch.setattr(correction_context, "build_direct_source_corpus", rebuild)
    result = await correction_context.resolve_lesson_correction(db, _actor(), LESSON)
    assert result.excerpts[0].text == rule.source_quote
    assert result.excerpts[0].citation.locator.startswith("span-v1:")
    altered = replace(corpus.documents[0], source_text=corpus.documents[0].source_text + " changed")
    async def changed(*_args, **_kwargs): return replace(corpus, documents=(altered,))
    monkeypatch.setattr(correction_context, "build_direct_source_corpus", changed)
    with pytest.raises(CorrectionError, match="lesson_source_provenance_unavailable"):
        await correction_context.resolve_lesson_correction(db, _actor(), LESSON)


def test_repeated_quote_wrong_revision_and_foreign_document_hold():
    corpus, rule = setup_span()
    doc = corpus.documents[0]
    repeated = replace(doc, source_text=doc.source_text + "\n" + rule.source_quote)
    assert working_text_references(replace(corpus, documents=(repeated,)), (rule,)) is None
    assert working_text_references(corpus, (replace(rule, source_revision="document:" + "b" * 64),)) is None
    assert working_text_references(corpus, (replace(rule, doc_id="foreign"),)) is None
    assert working_text_references(corpus, (rule, rule)) is None


def test_split_numeric_token_is_not_silently_reconstructed():
    corpus, rule = setup_span()
    text = "| Category | Amount 7 50 units |"
    doc = replace(corpus.documents[0], source_text=text)
    corpus = replace(corpus, documents=(doc,))
    candidate = replace(rule, source_quote="750", source_start=0, source_end=len(text))
    assert working_text_references(corpus, (candidate,)) is None


def test_adapter_falls_back_to_exact_working_span_and_keeps_review():
    corpus, rule = setup_span()
    lesson = V3Lesson("l", "title", "module", "body", ("r",))
    course = V3Course("c", "title", "a" * 64, (lesson,))
    output = v3_course_to_generation_artifacts(course, source_corpus=corpus, source_rules=(rule,),
                                               exact_narrative_facts=True)
    saved = output.content.modules[0].lessons[0]
    assert saved.source_references == working_text_references(corpus, (rule,))
    assert saved.source_validation_status == "needs_review"


def test_more_than_64_same_source_units_coalesce_without_dropping_rules():
    corpus, rule = setup_span()
    rules = tuple(replace(rule, rule_id=f"r{i}") for i in range(70))
    refs = working_text_references(corpus, rules)
    assert refs and len(refs) == 1
    assert all(refs[0]["start"] <= item.source_start and refs[0]["end"] >= item.source_end for item in rules)


def test_disjoint_over_limit_and_excess_excerpt_size_hold():
    corpus, rule = setup_span()
    words = [f"value-{i:03d}" for i in range(65)]
    text = " | ".join(words)
    doc = replace(corpus.documents[0], source_text=text)
    corpus = replace(corpus, documents=(doc,))
    rules = tuple(replace(rule, rule_id=f"r{i}", source_quote=word,
        source_start=text.index(word), source_end=text.index(word) + len(word)) for i, word in enumerate(words))
    assert working_text_references(corpus, rules) is None
    giant = "x" * 24_001
    corpus = replace(corpus, documents=(replace(doc, source_text=giant),))
    large_rule = replace(rule, source_quote=giant, source_start=0, source_end=len(giant))
    assert working_text_references(corpus, (large_rule,)) is None


def test_nested_adjacent_disjoint_and_unicode_source_spans():
    corpus, rule = setup_span()
    text = "猫ab🐈cd--ef"
    corpus = replace(corpus, documents=(replace(corpus.documents[0], source_text=text),))
    spans = ((0, 3), (1, 2), (3, 6), (8, 10))
    rules = tuple(replace(rule, rule_id=f"r{i}", source_quote=text[start:end],
                          source_start=start, source_end=end) for i, (start, end) in enumerate(spans))
    refs = working_text_references(corpus, rules)
    assert refs and [(ref["start"], ref["end"]) for ref in refs] == [(0, 6), (8, 10)]


def test_equal_offsets_across_documents_never_coalesce():
    from uuid import uuid4

    corpus, rule = setup_span()
    other_id = str(uuid4())
    other = replace(corpus.documents[0], doc_id=other_id)
    corpus = replace(corpus, documents=(*corpus.documents, other))
    refs = working_text_references(corpus, (rule, replace(rule, rule_id="r2", doc_id=other_id)))
    assert refs and len(refs) == 2 and {ref["doc_id"] for ref in refs} == {str(DOCUMENT), other_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("doc_id", "00000000-0000-0000-0000-000000000099"),
    ("source_revision", "document:" + "b" * 64),
    ("source_text_sha256", "0" * 64), ("span_sha256", "0" * 64),
    ("start", -1), ("end", 100000), ("start", True),
])
async def test_resolver_rejects_foreign_stale_and_malformed_spans(monkeypatch, field, value):
    corpus, rule = setup_span()
    refs = working_text_references(corpus, (rule,))
    db, lesson, *_ = _patch(monkeypatch)
    lesson.source_references = [{**refs[0], field: value}]
    async def rebuild(*_args, **_kwargs): return corpus
    monkeypatch.setattr(correction_context, "build_direct_source_corpus", rebuild)
    with pytest.raises(CorrectionError, match="lesson_source_provenance_unavailable"):
        await correction_context.resolve_lesson_correction(db, _actor(), LESSON)


@pytest.mark.asyncio
async def test_span_does_not_grant_foreign_tenant_access(monkeypatch):
    from uuid import uuid4

    from app.modules.methodologist_workbench.assignment_service import WorkbenchNotFound

    corpus, rule = setup_span()
    db, lesson, *_ = _patch(monkeypatch)
    lesson.source_references = working_text_references(corpus, (rule,))
    async def rebuild(*_args, **_kwargs): return corpus
    monkeypatch.setattr(correction_context, "build_direct_source_corpus", rebuild)
    with pytest.raises(WorkbenchNotFound):
        await correction_context.resolve_lesson_correction(db, _actor(tenant_id=uuid4()), LESSON)
