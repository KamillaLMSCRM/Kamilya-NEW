"""Contract probes for the source -> plan -> lesson -> question chain.

The literals in the synthetic corpus are the independent oracle; the engine
must not derive the expected outcome from its own output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
)
from app.modules.ai.document_passport import build_document_passport
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.ingestion import DocumentChunker, DocumentConverter, _local_convert

CORPUS = json.loads(
    (
        Path(__file__).parents[1]
        / "fixtures"
        / "course_generation_backward"
        / "corpus.json"
    ).read_text(encoding="utf-8")
)


def _direct_source(case: dict) -> DirectSourceCorpus:
    document_id = f"synthetic-{case['id']}"
    revision = f"document:synthetic-{case['id']}"
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"{document_id}:{index}",
            doc_id=document_id,
            doc_name=case["filename"],
            title=case["title"],
            headings=(chunk["heading"],),
            text=chunk["text"],
            source_revision=revision,
            chunk_index=index,
        )
        for index, chunk in enumerate(case["chunks"])
    )
    return DirectSourceCorpus(
        tenant_id="synthetic-quality-corpus",
        documents=(
            DirectSourceDocument(
                doc_id=document_id,
                title=case["title"],
                filename=case["filename"],
                category="training_material",
                source_revision=revision,
                chunks=chunks,
            ),
        ),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=len(chunks),
    )


def _converted_source(case: dict, markdown: str) -> DirectSourceCorpus:
    document_id = f"converted-{case['id']}"
    rows = DocumentChunker().chunk_markdown(markdown, document_id, case["filename"])
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"{document_id}:{index}",
            doc_id=document_id,
            doc_name=case["filename"],
            title=case["title"],
            headings=tuple(json.loads(row["metadata"]["headings"])),
            text=row["text"],
            source_revision="converted-synthetic-v1",
            chunk_index=index,
        )
        for index, row in enumerate(rows)
    )
    return DirectSourceCorpus(
        tenant_id="synthetic-quality-corpus",
        documents=(DirectSourceDocument(
            doc_id=document_id,
            title=case["title"],
            filename=case["filename"],
            category="training_material",
            source_revision="converted-synthetic-v1",
            chunks=chunks,
        ),),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=len(chunks),
    )


@pytest.mark.parametrize(
    "case", CORPUS["cases"], ids=lambda case: case["id"]
)
def test_source_plan_and_draft_respect_document_information_density(case: dict) -> None:
    source = build_evidence_source(_direct_source(case)).document
    result = EvidenceCourseEngine().generate_from_document(source)
    gold = case["gold"]

    assert 0 < len(result.course.lessons) <= gold["max_lessons"]
    assert len(result.assessment.questions) <= gold["distinct_assessable_decisions"]
    assert result.evaluation.quota_padding_count == 0
    assert result.evaluation.unsupported_claim_count == 0
    assert result.evaluation.cross_lesson_question_count == 0
    for phrase in gold["must_preserve"]:
        assert any(phrase in fact.value for fact in result.admitted_facts)
    for phrase in gold["must_not_claim"]:
        assert all(phrase not in lesson.content for lesson in result.course.lessons)
    for section in gold.get("supporting_sections", []):
        assert any(section in title for title in result.document_plan.supporting_sections)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["id"])
def test_question_targets_remain_inside_one_source_owned_lesson(case: dict) -> None:
    result = EvidenceCourseEngine().generate_from_document(
        build_evidence_source(_direct_source(case)).document
    )
    facts = {fact.fact_id: fact for fact in result.admitted_facts}
    count = 0
    for lesson in result.course.lessons:
        axes = derive_assessment_axes(
            lesson, [facts[fact_id] for fact_id in lesson.fact_ids],
            block_id=f"synthetic-{lesson.lesson_id}",
        )
        count += len(axes)
        for axis in axes:
            assert axis.primary_fact_id in lesson.fact_ids
            assert all(fact_id in lesson.fact_ids for fact_id in axis.evidence_fact_ids)
            assert "? рабочих дней" not in axis.correct_value
            if case["id"] == "micro_one_rule":
                assert "до передачи товара" in axis.correct_value
    assert count >= 1
    if case["id"] == "micro_one_rule":
        assert count == 1


@pytest.mark.asyncio
async def test_real_spreadsheet_conversion_preserves_both_sheet_roles() -> None:
    path = Path(__file__).parents[1] / "fixtures" / "course_generation_backward" / "collections.xlsx"
    converted = await DocumentConverter().convert(str(path))

    assert converted["metadata"]["engine"] == "openpyxl"
    assert "# [Worksheet] Коллекции" in converted["markdown"]
    assert "# [Worksheet] Номенклатура" in converted["markdown"]
    assert "| Материал фасада | МДФ | ЛДСП |" in converted["markdown"]
    assert "| N-001 | Шкаф 80 см | Север | 4 |" in converted["markdown"]
    case = next(item for item in CORPUS["cases"] if item["id"] == "spreadsheet_primary_auxiliary")
    source = build_evidence_source(_converted_source(case, converted["markdown"])).document
    result = EvidenceCourseEngine().generate_from_document(source)
    assert len(result.course.lessons) <= case["gold"]["max_lessons"]
    assert any("Номенклатура" in name for name in result.document_plan.supporting_sections)


@pytest.mark.asyncio
async def test_text_layer_pdf_conversion_retains_rules_and_section_order() -> None:
    path = Path(__file__).parents[1] / "fixtures" / "course_generation_backward" / "structured_policy.pdf"
    converted = await _local_convert(str(path))
    text = converted["markdown"]

    assert converted["metadata"]["engine"] == "pypdf"
    assert text.index("1. Проверка документов") < text.index("2. Осмотр товара")
    assert "до разгрузки" in text
    assert "до подписания" in text
    case = next(item for item in CORPUS["cases"] if item["id"] == "structured_policy")
    source = build_evidence_source(_converted_source(case, text)).document
    result = EvidenceCourseEngine().generate_from_document(source)
    assert 0 < len(result.course.lessons) <= case["gold"]["max_lessons"]
    for phrase in case["gold"]["must_preserve"]:
        assert any(phrase in fact.value for fact in result.admitted_facts)


def test_production_style_plaintext_pdf_sections_remain_separate() -> None:
    # Remote MarkItDown returns numbered nominal headings without Markdown '#'.
    # This is distinct from the pypdf local fallback used by the PDF fixture test.
    markdown = (
        "Приёмка товара\n\n"
        "1. Проверка документов\n\n"
        "Сотрудник сверяет номер накладной с номером заказа до разгрузки.\n\n"
        "Если номера не совпадают, разгрузку не начинают и сообщают руководителю смены.\n\n"
        "2. Осмотр товара\n\n"
        "После сверки документов сотрудник осматривает упаковку.\n\n"
        "Повреждение упаковки фиксируют в акте приёмки до подписания накладной."
    )
    case = next(item for item in CORPUS["cases"] if item["id"] == "structured_policy")
    rows = DocumentChunker().chunk_markdown(markdown, "pdf-plain", case["filename"])
    assert len(rows) == 2
    assert json.loads(rows[0]["metadata"]["headings"]) == ["1. Проверка документов"]
    assert json.loads(rows[1]["metadata"]["headings"]) == ["2. Осмотр товара"]
    assert "разгрузку" not in rows[1]["text"]
    assert "упаковку" not in rows[0]["text"]
    result = EvidenceCourseEngine().generate_from_document(
        build_evidence_source(_converted_source(case, markdown)).document
    )
    assert len(result.course.lessons) == 2
    assert all(
        any(phrase in fact.value for fact in result.admitted_facts)
        for phrase in case["gold"]["must_preserve"]
    )


def test_numbered_action_line_is_not_promoted_to_pdf_section() -> None:
    markdown = (
        "Порядок приёмки\n\n1. Сверьте номер накладной до разгрузки.\n\n"
        "2. Сообщите о несовпадении руководителю смены."
    )
    rows = DocumentChunker().chunk_markdown(markdown, "actions", "actions.pdf")
    assert len(rows) == 1
    assert json.loads(rows[0]["metadata"]["headings"]) == []


def test_two_short_numbered_rules_are_not_collapsed_to_one_lesson() -> None:
    markdown = (
        "1. Проверка допуска\n\n"
        "Перед началом смены сотрудник проверяет действующий допуск.\n\n"
        "2. Регистрация результата\n\n"
        "После проверки сотрудник фиксирует результат в журнале допуска."
    )
    case = {"id": "two-short-rules", "title": "Порядок допуска", "filename": "rules.pdf"}
    source = build_evidence_source(_converted_source(case, markdown)).document
    result = EvidenceCourseEngine().generate_from_document(source)
    assert len(result.course.lessons) == 2


def test_nested_numbered_pdf_headings_keep_distinct_boundaries() -> None:
    markdown = (
        "1.1 Проверка номера заказа\n\n"
        "Сотрудник проверяет номер заказа перед началом обработки.\n\n"
        "1.2 Проверка упаковки\n\n"
        "После этого сотрудник проверяет целостность упаковки."
    )
    rows = DocumentChunker().chunk_markdown(markdown, "nested", "nested.pdf")
    assert [json.loads(row["metadata"]["headings"]) for row in rows] == [
        ["1.1 Проверка номера заказа"], ["1.2 Проверка упаковки"]
    ]
    case = {"id": "nested-rules", "title": "Порядок проверки", "filename": "nested.pdf"}
    corpus = _converted_source(case, markdown)
    assert build_document_passport(corpus).primary_sections == (
        "1.1 Проверка номера заказа", "1.2 Проверка упаковки"
    )
    source = build_evidence_source(corpus).document
    assert len(EvidenceCourseEngine().generate_from_document(source).course.lessons) == 2


def test_actual_remote_converter_text_preserves_wrapped_rule_and_sections() -> None:
    fixture = (
        Path(__file__).parents[1] / "fixtures" / "course_generation_backward"
        / "structured_policy_markitdown.md"
    )
    markdown = fixture.read_text(encoding="utf-8")
    case = next(item for item in CORPUS["cases"] if item["id"] == "structured_policy")
    rows = DocumentChunker().chunk_markdown(markdown, "remote-capture", case["filename"])
    assert len(rows) == 2
    assert [json.loads(row["metadata"]["headings"]) for row in rows] == [
        ["1. Проверка документов"], ["2. Осмотр товара"]
    ]
    result = EvidenceCourseEngine().generate_from_document(
        build_evidence_source(_converted_source(case, markdown)).document
    )
    assert len(result.course.lessons) == 2
    assert any(
        "сообщают руководителю смены" in fact.value.replace("\n", " ")
        for fact in result.admitted_facts
    )
    assert any(
        "до подписания накладной" in fact.value.replace("\n", " ")
        for fact in result.admitted_facts
    )
