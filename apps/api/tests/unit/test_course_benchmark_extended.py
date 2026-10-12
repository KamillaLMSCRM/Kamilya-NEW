from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from scripts.dev.course_quality_eval.benchmark import corpus_for_case, load_suite

from app.modules.ai.evidence_engine.application import _reassemble_section_chunks, build_evidence_source
from app.modules.ai.evidence_engine.engine import admit_document_facts
from app.modules.ai.ingestion import DocumentChunker
from app.modules.ai.source_tables import markdown_tables

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "course_benchmark_extended_v1.json"
EXPECTED = {
    "equipment-handover-09": ("development", 600, 900, 15),
    "mixed-table-policy-10": ("development", 500, 800, 14),
    "exceptions-deadlines-11": ("holdout", 400, 600, 15),
}


def test_extended_suite_is_frozen_and_source_owned():
    cases = load_suite(FIXTURE)
    assert [case["id"] for case in cases] == list(EXPECTED)
    for case in cases:
        split, minimum, maximum, gold_count = EXPECTED[case["id"]]
        assert case["split"] == split
        assert case["expected"] == "draft"
        assert minimum <= len(case["source"].split()) <= maximum
        assert len(case["required_claims"]) == gold_count
        assert len(case["forbidden_claims"]) >= 3
        assert sum(claim["critical"] for claim in case["required_claims"]) >= 3


def test_extended_gold_is_distributed_and_corpus_locators_are_continuous():
    cases = load_suite(FIXTURE)
    for case in cases:
        source = " ".join(case["source"].casefold().split())
        positions = [source.index(" ".join(claim["quote"].casefold().split()))
                     for claim in case["required_claims"]]
        length = len(source)
        assert min(positions) < length / 3
        assert max(positions) > length * 2 / 3
        assert sum(length / 3 <= position <= length * 2 / 3 for position in positions) >= 3

        corpus = corpus_for_case(case)
        document = corpus.documents[0]
        assert len(document.chunks) > 1
        assert document.doc_id == case["id"]
        expected_revision = "document:" + hashlib.sha256(case["source"].encode()).hexdigest()
        assert document.source_revision == expected_revision
        assert [chunk.chunk_index for chunk in document.chunks] == list(range(len(document.chunks)))
        assert {chunk.doc_id for chunk in document.chunks} == {case["id"]}
        assert {chunk.doc_name for chunk in document.chunks} == {case["filename"]}
        assert {chunk.source_revision for chunk in document.chunks} == {expected_revision}


@pytest.mark.parametrize("case_id", list(EXPECTED))
def test_long_source_admission_preserves_prose_and_complete_table_rows(case_id):
    case = next(case for case in load_suite(FIXTURE) if case["id"] == case_id)
    document = build_evidence_source(corpus_for_case(case)).document
    admitted, _supporting, _duplicates = admit_document_facts(document)
    prose = " ".join(" ".join(fact.value.split()) for fact in admitted)
    cells = {(fact.subject, fact.attribute, fact.value) for fact in admitted
             if "table=" in fact.source_locator}
    for claim in case["required_claims"]:
        if not claim["quote"].startswith("|"):
            assert " ".join(claim["quote"].split()) in prose, claim["id"]
    for headers, rows in markdown_tables(case["source"]):
        for row, _raw in rows:
            for column, value in zip(headers[1:], row[1:], strict=True):
                assert (row[0], column, value) in cells


def test_genuine_heading_does_not_relabel_previous_section_overlap():
    chunks = DocumentChunker().chunk_markdown(
        "# Документ\n\n## Первый раздел\n\nПредыдущее правило действует только здесь."
        "\n\n## Второй раздел\n\nНовое правило действует отдельно.", "boundaries", "boundaries.md",
    )
    second = next(chunk for chunk in chunks if "Второй раздел" in chunk["metadata"]["headings"])
    assert second["text"].startswith("## Второй раздел")
    assert "Предыдущее правило" not in second["text"]


@pytest.mark.parametrize("boundary", ["gap", "duplicate", "revision", "heading", "worksheet"])
def test_section_reassembly_never_crosses_unproven_boundary(boundary):
    first = corpus_for_case(load_suite(FIXTURE)[2]).documents[0].chunks[0]
    first = replace(first, text="Начало правила без продолжения", chunk_index=0, headings=("Правило",))
    second = replace(first, text="продолжение правила.", chunk_index=1, chunk_id="second")
    if boundary == "gap":
        second = replace(second, chunk_index=2)
    elif boundary == "duplicate":
        second = replace(second, chunk_index=0)
    elif boundary == "revision":
        second = replace(second, source_revision="different-revision")
    elif boundary == "heading":
        second = replace(second, headings=("Другое правило",))
    else:
        first = replace(first, headings=("[Worksheet] Справочник",))
        second = replace(second, headings=first.headings)
    assert _reassemble_section_chunks((first, second)) == (first, second)


def test_section_reassembly_preserves_all_contributing_chunk_ids():
    first = corpus_for_case(load_suite(FIXTURE)[2]).documents[0].chunks[0]
    first = replace(first, text="Начало правила и общее подтвержденное продолжение", chunk_index=0)
    second = replace(first, text="и общее подтвержденное продолжение правила.", chunk_index=1, chunk_id="second")
    (merged,) = _reassemble_section_chunks((first, second))
    assert merged.chunk_id == first.chunk_id + ",second"
    assert merged.text == "Начало правила и общее подтвержденное продолжение правила."


def test_ordinary_tables_follow_their_rules_not_precede_document_introduction():
    case = load_suite(FIXTURE)[2]
    document = build_evidence_source(corpus_for_case(case)).document
    titles = list(dict.fromkeys(section.title for section in document.sections))
    headings = [line.removeprefix("## ").strip() for line in case["source"].splitlines()
                if line.startswith("## ")]
    assert [title for title in titles if title in headings] == headings
    for title in headings:
        matching = [section for section in document.sections if section.title == title]
        if any(":table:" in section.section_id for section in matching):
            assert ":table:" not in matching[0].section_id
