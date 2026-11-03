"""Source references must come from uniquely bound owned rule evidence."""
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.models import RuleEntity, V3Course, V3Lesson


def data():
    def document(doc_id, quote):
        chunk = DirectSourceChunk(chunk_id="chunk-" + doc_id, doc_id=doc_id, doc_name=doc_id,
            title=doc_id, headings=("Heading",), text="prefix " + quote + " suffix", source_revision="rev", chunk_index=0)
        doc = DirectSourceDocument(doc_id=doc_id, title=doc_id, filename=doc_id, category="general",
            source_revision="rev", chunks=(chunk,), source_text=chunk.text)
        rule = RuleEntity(rule_id="rule-" + doc_id, section="s", title="t", statement=quote,
            source_quote=quote, doc_id=doc_id, source_revision="rev", source_start=7, source_end=7 + len(quote))
        return doc, rule
    d1, r1 = document("d1", "one unique rule")
    d2, r2 = document("d2", "other unique rule")
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(d1, d2), total_chars=100, total_chunks=2)
    lesson = V3Lesson(lesson_id="l1", title="title", module_title="module", content="content",
                      covered_rule_ids=("rule-d1",))
    course = V3Course(course_id="course", title="title", document_sha256="a" * 64,
                      lessons=(lesson,), quality_verdict="verified")
    return corpus, (r1, r2), course


def test_owned_rule_maps_only_its_uniquely_owned_document():
    corpus, rules, course = data()
    result = v3_course_to_generation_artifacts(course, source_document_ids=["d1", "d2"],
                                               source_corpus=corpus, source_rules=rules)
    lesson = result.content.modules[0].lessons[0]
    assert lesson.source_references == [{"doc_id": "d1"}]
    assert result.structure.modules[0].lessons[0].source_doc_ids == ["d1"]


@pytest.mark.parametrize("problem", ["stale", "repeat", "duplicate_rule", "duplicate_document"])
def test_ambiguous_or_stale_attribution_holds_without_guessing(problem):
    corpus, rules, course = data()
    d1, d2 = corpus.documents
    if problem == "stale":
        rules = (replace(rules[0], source_revision="old"), rules[1])
    elif problem == "repeat":
        d1 = replace(d1, source_text=d1.source_text + " one unique rule")
    elif problem == "duplicate_rule":
        rules = (rules[0], rules[0], rules[1])
    else:
        d2 = replace(d2, doc_id="d1", source_revision="other")
    corpus = replace(corpus, documents=(d1, d2))
    result = v3_course_to_generation_artifacts(course, source_corpus=corpus, source_rules=rules)
    lesson = result.content.modules[0].lessons[0]
    assert lesson.source_references == []
    assert lesson.source_validation_status == "needs_review"
    assert result.diagnostics["requires_source_review"] is True


def test_legacy_default_keeps_document_only_references():
    _, _, course = data()
    result = v3_course_to_generation_artifacts(course, source_document_ids=["d1", "d2"])
    assert result.content.modules[0].lessons[0].source_references == [{"doc_id": "d1"}, {"doc_id": "d2"}]


def test_transient_direct_chunk_ids_are_never_published():
    corpus, rules, course = data()
    doc = corpus.documents[0]
    transient = replace(doc.chunks[0], chunk_id="direct:d1:0")
    corpus = replace(corpus, documents=(replace(doc, chunks=(transient,)), corpus.documents[1]))
    result = v3_course_to_generation_artifacts(course, source_corpus=corpus, source_rules=rules)
    assert result.content.modules[0].lessons[0].source_references == [{"doc_id": "d1"}]


def test_missing_unique_rule_fails_closed():
    corpus, rules, course = data()
    lesson = replace(course.lessons[0], covered_rule_ids=("missing",))
    result = v3_course_to_generation_artifacts(replace(course, lessons=(lesson,)), source_corpus=corpus, source_rules=rules)
    assert result.content.modules[0].lessons[0].source_references == []
    assert result.content.modules[0].lessons[0].source_validation_status == "needs_review"
    assert result.diagnostics["requires_source_review"] is True


def test_legacy_preserves_duplicate_source_ids_and_diagnostics_shape():
    _, _, course = data()
    result = v3_course_to_generation_artifacts(course, source_document_ids=["d1", "d1", "d2"])
    assert result.structure.modules[0].lessons[0].source_doc_ids == ["d1", "d1", "d2"]
    assert result.content.modules[0].lessons[0].source_references == [{"doc_id": "d1"}, {"doc_id": "d1"}, {"doc_id": "d2"}]
    assert set(result.diagnostics) == {"generation_engine", "document_sha256", "lessons_count", "assessments_count",
                                       "quality_verdict", "validation_report", "violations", "requires_source_review"}
