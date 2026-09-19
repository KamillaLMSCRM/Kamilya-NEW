from __future__ import annotations

import json

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
)
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.ingestion import DocumentChunker


def _corpus(*chunks: DirectSourceChunk) -> DirectSourceCorpus:
    document = DirectSourceDocument(
        doc_id="synthetic-policy",
        title="Operations handbook",
        filename="operations-handbook.pdf",
        category="training_material",
        source_revision="document:synthetic-sha",
        chunks=chunks,
    )
    return DirectSourceCorpus(
        tenant_id="synthetic-tenant",
        documents=(document,),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=len(chunks),
    )


def _chunk(index: int, heading: str, text: str) -> DirectSourceChunk:
    return DirectSourceChunk(
        chunk_id=f"chunk-{index}",
        doc_id="synthetic-policy",
        doc_name="operations-handbook.pdf",
        title="Operations handbook",
        headings=(heading,),
        text=text,
        source_revision="document:synthetic-sha",
        chunk_index=index,
    )


def _docling_style_corpus(markdown: str) -> DirectSourceCorpus:
    raw_chunks = DocumentChunker(chunk_size=10_000, chunk_overlap=0).chunk_markdown(
        markdown, "synthetic-policy", "operations-handbook.pdf"
    )
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"chunk-{index}",
            doc_id="synthetic-policy",
            doc_name="operations-handbook.pdf",
            title="Operations handbook",
            headings=tuple(json.loads(raw["metadata"]["headings"])),
            text=raw["text"],
            source_revision="document:synthetic-sha",
            chunk_index=index,
        )
        for index, raw in enumerate(raw_chunks)
    )
    return _corpus(*chunks)


def test_docling_navigation_prefix_and_wrapped_heading_do_not_become_lessons() -> None:
    corpus = _docling_style_corpus(
        "<!-- image -->\n\n"
        "# Operations handbook\n\n"
        "Example City - 2025.\n\n"
        "1. General rules\n"
        "2. Request review procedure\n\n"
        "## Contents:\n\n"
        "1. General rules\n"
        "2. Request review procedure\n\n"
        "## 1. GENERAL RULES\n\n"
        "Staff verify the seal before unloading.\n\n"
        "## 2. REQUEST REVIEW\n\n"
        "## PROCEDURE\n\n"
        "Before storage, staff complete:\n\n"
        "1. record the receipt\n\n"
        "2. place the goods in the secured area\n\n"
        "The service fee is 2.5 percent if storage lasts more than 30 days."
    )

    bundle = build_evidence_source(corpus)
    result = EvidenceCourseEngine().generate_from_document(bundle.document)

    assert [section.title for section in bundle.document.sections] == [
        "1. GENERAL RULES",
        "2. REQUEST REVIEW PROCEDURE",
    ]
    assert [lesson.title for lesson in result.course.lessons] == [
        "GENERAL RULES",
        "REQUEST REVIEW PROCEDURE",
    ]
    assert [fact.value for fact in bundle.all_facts] == [
        "Staff verify the seal before unloading.",
        "Before storage, staff complete: 1. record the receipt 2. place the goods in the secured area",
        "The service fee is 2.5 percent if storage lasts more than 30 days.",
    ]
    assert all(
        "doc_id=synthetic-policy" in fact.source_locator
        and "source_revision=document:synthetic-sha" in fact.source_locator
        for fact in bundle.all_facts
    )


def test_meaningful_rule_before_contents_remains_source_evidence() -> None:
    corpus = _docling_style_corpus(
        "# Operations handbook\n\n"
        "Staff verify the seal before unloading.\n\n"
        "## Contents:\n\n"
        "1. General rules\n\n"
        "## 1. GENERAL RULES\n\n"
        "Staff record the receipt after unloading."
    )

    bundle = build_evidence_source(corpus)

    assert [section.title for section in bundle.document.sections] == [
        "Operations handbook",
        "1. GENERAL RULES",
    ]
    assert [fact.value for fact in bundle.all_facts] == [
        "Staff verify the seal before unloading.",
        "Staff record the receipt after unloading.",
    ]


def test_uppercase_ordinary_sentence_is_not_consumed_as_a_heading_fragment() -> None:
    corpus = _docling_style_corpus(
        "## 2. INCIDENT RESPONSE\n\n"
        "NOTIFY THE MANAGER IMMEDIATELY.\n\n"
        "Record the incident in the register."
    )

    bundle = build_evidence_source(corpus)

    assert [section.title for section in bundle.document.sections] == ["2. INCIDENT RESPONSE"]
    assert [fact.value for fact in bundle.all_facts] == [
        "NOTIFY THE MANAGER IMMEDIATELY.",
        "Record the incident in the register.",
    ]


def test_ocr_duplicate_toc_number_does_not_hide_matching_body_title():
    corpus = _docling_style_corpus(
        "# Operations handbook\n\nExample City - 2025.\n\n"
        "1. General rules\n2. 2.\n3. Incident response\n\n"
        "## Contents:\n\n"
        "## 1. GENERAL RULES\n\nStaff verify the seal before unloading.\n\n"
        "## 2. INCIDENT RESPONSE\n\nStaff record every incident."
    )
    bundle = build_evidence_source(corpus)
    assert [fact.value for fact in bundle.all_facts] == [
        "Staff verify the seal before unloading.", "Staff record every incident.",
    ]


def test_overlapping_continuation_heading_is_appended_only_once():
    corpus = _corpus(
        _chunk(0, "2. REQUEST REVIEW", "## 2. REQUEST REVIEW"),
        _chunk(1, "PROCEDURE", "## 2. REQUEST REVIEW\n\n## PROCEDURE\n\nStaff record the receipt."),
        _chunk(2, "PROCEDURE", "Staff record the receipt.\n\nStaff verify the seal."),
    )
    bundle = build_evidence_source(corpus)
    assert [section.title for section in bundle.document.sections] == ["2. REQUEST REVIEW PROCEDURE"]
    assert [fact.value for fact in bundle.all_facts] == [
        "Staff record the receipt.", "Staff verify the seal.",
    ]


def test_numbered_prose_before_contents_is_not_mistaken_for_a_toc() -> None:
    corpus = _docling_style_corpus(
        "# Operations handbook\n\n"
        "1. Staff must verify identity.\n"
        "2. Staff must record consent.\n\n"
        "## Contents:\n\n"
        "1. System setup\n"
        "2. Reporting\n\n"
        "## 1. SYSTEM SETUP\n\n"
        "Configure the secure workstation.\n\n"
        "## 2. REPORTING\n\n"
        "Submit the daily report."
    )

    bundle = build_evidence_source(corpus)

    assert [section.title for section in bundle.document.sections] == [
        "Operations handbook",
        "1. SYSTEM SETUP",
        "2. REPORTING",
    ]
    assert [fact.value for fact in bundle.all_facts] == [
        "1. Staff must verify identity.",
        "2. Staff must record consent.",
        "Configure the secure workstation.",
        "Submit the daily report.",
    ]
