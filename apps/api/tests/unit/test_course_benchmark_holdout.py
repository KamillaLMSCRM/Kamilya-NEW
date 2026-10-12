from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.dev.course_quality_eval.benchmark import corpus_for_case, load_suite

from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.engine import admit_document_facts
from app.modules.ai.evidence_engine.models import LessonDraft
from app.modules.ai.source_tables import markdown_tables

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "course_benchmark_holdout_v2.json"


def test_complex_holdout_is_source_owned_and_bounded():
    cases = load_suite(FIXTURE)
    assert len(cases) == 1
    case = cases[0]
    assert case["id"] == "complex-change-control-12"
    assert case["split"] == "holdout"
    assert case["expected"] == "draft"
    assert 800 <= len(case["source"].split()) <= 1100
    assert 7 <= case["source"].count("## ") <= 9
    assert len(case["required_claims"]) == 23
    assert len(case["forbidden_claims"]) >= 5
    assert sum(claim["critical"] for claim in case["required_claims"]) >= 20


def test_complex_holdout_gold_is_distributed_and_document_identity_is_stable():
    case = load_suite(FIXTURE)[0]
    normalized = " ".join(case["source"].casefold().split())
    positions = [normalized.index(" ".join(claim["quote"].casefold().split()))
                 for claim in case["required_claims"]]
    source_length = len(normalized)
    assert min(positions) < source_length / 3
    assert max(positions) > source_length * 2 / 3
    assert sum(source_length / 3 <= pos <= source_length * 2 / 3 for pos in positions) >= 6
    assert all(case["source"].count(claim["quote"]) == 1 for claim in case["required_claims"])

    corpus = corpus_for_case(case)
    document = corpus.documents[0]
    assert len(document.chunks) > 1
    expected_revision = "document:" + hashlib.sha256(case["source"].encode()).hexdigest()
    assert document.doc_id == case["id"]
    assert document.filename == case["filename"]
    assert document.source_revision == expected_revision
    assert [chunk.chunk_index for chunk in document.chunks] == list(range(len(document.chunks)))
    assert {chunk.doc_id for chunk in document.chunks} == {case["id"]}
    assert {chunk.doc_name for chunk in document.chunks} == {case["filename"]}
    assert {chunk.source_revision for chunk in document.chunks} == {expected_revision}


def test_numbered_operational_sections_and_every_table_cell_enter_curriculum():
    case = load_suite(FIXTURE)[0]
    document = build_evidence_source(corpus_for_case(case)).document
    admitted, _, _ = admit_document_facts(document)
    prose = " ".join(" ".join(fact.value.split()) for fact in admitted)
    cells = {(fact.subject, fact.attribute, fact.value) for fact in admitted
             if "table=" in fact.source_locator}
    for claim in case["required_claims"]:
        if not claim["quote"].startswith("|"):
            assert " ".join(claim["quote"].split()) in prose, claim["id"]
    for headers, rows in markdown_tables(case["source"]):
        for row, _ in rows:
            for column, value in zip(headers[1:], row[1:], strict=True):
                assert (row[0], column, value) in cells


def test_intro_assessment_prefers_explicit_actionable_rule_over_compound_scope():
    case = load_suite(FIXTURE)[0]
    admitted, _, _ = admit_document_facts(build_evidence_source(corpus_for_case(case)).document)
    fact = admitted[0]
    lesson = LessonDraft("intro", "Intro", "Назначение", "Применять порядок",
                         fact.value, (fact.fact_id,), (), 1)
    (axis,) = derive_assessment_axes(lesson, [fact], block_id="intro")
    assert axis.correct_value == next(claim["quote"] for claim in case["required_claims"]
                                      if claim["id"] == "separation")
