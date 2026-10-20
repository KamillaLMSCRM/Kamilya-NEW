"""Regression for physical ordering across prose and ordinary Markdown tables."""

from __future__ import annotations

import json

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.ingestion import DocumentChunker


def _corpus(markdown: str, *, doc_id: str, filename: str) -> DirectSourceCorpus:
    rows = DocumentChunker().chunk_markdown(markdown, doc_id, filename)
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"{doc_id}:chunk-{index}",
            doc_id=doc_id,
            doc_name=filename,
            title=filename,
            headings=tuple(json.loads(row["metadata"]["headings"])),
            text=row["text"],
            source_revision="revision-order-v1",
            chunk_index=index,
        )
        for index, row in enumerate(rows)
    )
    return DirectSourceCorpus(
        tenant_id="synthetic-source-order",
        documents=(DirectSourceDocument(
            doc_id=doc_id,
            title=filename,
            filename=filename,
            category="training_material",
            source_revision="revision-order-v1",
            chunks=chunks,
        ),),
        total_chars=len(markdown),
        total_chunks=len(chunks),
    )


def _ordered_lesson_facts(result):
    by_id = {fact.fact_id: fact for fact in result.admitted_facts}
    return [by_id[fact_id] for lesson in result.evidence_plan for fact_id in lesson.fact_ids]


def test_repeated_cover_signature_does_not_abort_mixed_source_teaching_order() -> None:
    markdown = (
        "Генеральный директор\n\n"
        "Введение. Перед началом работ сверяют комплект документов.\n\n"
        "| Категория | Город | Лимит |\n|---|---|---:|\n"
        "| Первая | Северный | 700 000 тенге |\n\n"
        "После проверки лимита оформляют решение.\n\n"
        "| Проверка | Исполнитель | Порядок |\n|---|---|---|\n"
        "| Комплексная | Инспектор | До подписания договора |\n\n"
        "Ответственный сотрудник фиксирует результат проверки.\n\n"
        "Генеральный директор"
    )
    source = build_evidence_source(
        _corpus(markdown, doc_id="mixed-order", filename="source-course.md")
    ).document

    signature_facts = [
        fact for section in source.sections for fact in section.facts
        if "Генеральный директор" in fact.value
    ]
    assert signature_facts
    assert all(fact.uncertainty == "source_cover_signature" for fact in signature_facts)

    result = EvidenceCourseEngine().generate_from_document(source)
    ordered = _ordered_lesson_facts(result)
    teachable_values = [fact.value for fact in ordered]
    expected_markers = [
        "Введение.",
        "700 000 тенге",
        "После проверки лимита",
        "До подписания договора",
        "Ответственный сотрудник",
    ]
    positions = [next(i for i, value in enumerate(teachable_values) if marker in value)
                 for marker in expected_markers]
    assert positions == sorted(positions)
    assert all("Генеральный директор" not in value for value in teachable_values)

    threshold = next(fact for fact in ordered if fact.value == "700 000 тенге")
    assert threshold.subject == "Первая"
    assert threshold.attribute == "Лимит"
    assert "row=2" in threshold.source_locator
    assert "column=3" in threshold.source_locator
    procedure = next(fact for fact in ordered if fact.value == "До подписания договора")
    assert procedure.subject == "Комплексная"
    assert procedure.attribute == "Порядок"
    assert "row=2" in procedure.source_locator
    assert "column=3" in procedure.source_locator


def test_repeated_operational_text_remains_ambiguous_and_worksheet_order_is_stable() -> None:
    markdown = (
        "# [Worksheet] Лимиты\n\n"
        "| Категория | Порог |\n|---|---:|\n| Первая | 700 000 тенге |\n\n"
        "# [Worksheet] Порядок\n\n"
        "| Шаг | Срок |\n|---|---|\n| Проверка | До подписания договора |\n\n"
        "# [Worksheet] Примечание\n\n"
        "| Правило | Статус |\n|---|---|\n"
        "| Проверка | До подписания договора |"
    )
    source = build_evidence_source(
        _corpus(markdown, doc_id="worksheet-order", filename="worksheet.md")
    ).document

    procedure_facts = [
        fact for section in source.sections for fact in section.facts
        if fact.value == "До подписания договора"
    ]
    assert len(procedure_facts) == 2
    assert len({fact.fact_id for fact in procedure_facts}) == 2
    assert len({fact.source_locator for fact in procedure_facts}) == 2
    assert [section.title for section in source.sections] == ["Лимиты", "Порядок", "Примечание"]
    roles_before_engine = [section.role for section in source.sections]
    for fact in procedure_facts:
        assert "До подписания договора" in fact.value
        assert "row=2" in fact.source_locator
        assert "column=2" in fact.source_locator

    result = EvidenceCourseEngine().generate_from_document(source)
    assert [section.role for section in source.sections] == roles_before_engine
    primary_titles = [section.title for section in source.sections if section.role == "primary"]
    assert [lesson.module_title for lesson in result.evidence_plan] == primary_titles


def test_unheaded_table_only_lesson_title_uses_table_subject_not_filename_part() -> None:
    markdown = (
        "| Категория | Город | Лимит |\n|---|---|---:|\n"
        "| Первая | Северный | 700 000 тенге |\n"
        "| Вторая | Южный | 1 200 000 тенге |"
    )
    source = build_evidence_source(
        _corpus(markdown, doc_id="table-title", filename="opaque-source-name.md")
    ).document
    result = EvidenceCourseEngine().generate_from_document(source)

    titles = [lesson.title for lesson in result.evidence_plan]
    assert titles
    assert all("opaque-source-name" not in title.casefold() for title in titles)
    title_and_objective = " ".join(
        f"{lesson.title} {lesson.objective}" for lesson in result.evidence_plan
    )
    assert "Первая" in title_and_objective
    assert "Вторая" in title_and_objective
    assert "Лимит" in title_and_objective


def test_repeated_operational_prose_does_not_gain_an_invented_source_position() -> None:
    source = build_evidence_source(_corpus(
        "# 1. Порядок проверки\n\n"
        "Сотрудник обязан сверить комплект документов.\n\n"
        "| Категория | Лимит |\n|---|---:|\n| Первая | 700 000 тенге |\n\n"
        "Сотрудник обязан сверить комплект документов.",
        doc_id="ambiguous-ordinary-order", filename="ambiguous.md",
    )).document
    primary = [section for section in source.sections if section.role == "primary"]
    assert primary
    assert not any(":source-run:" in section.section_id for section in primary)
    repeated = [fact for section in primary for fact in section.facts
                if "Сотрудник обязан сверить комплект документов." in fact.value]
    assert repeated
    assert all(fact.confidence >= 0.8 and fact.uncertainty == "" for fact in repeated)
    assert any(fact.value == "700 000 тенге" for section in primary for fact in section.facts)


def test_large_ordinary_table_keeps_a_compact_source_label_not_filename() -> None:
    rows = "\n".join(f"| Региональная категория номер {i} | {i * 100} тенге |" for i in range(1, 7))
    source = build_evidence_source(_corpus(
        "| Категория | Лимит |\n|---|---:|\n" + rows,
        doc_id="large-table-title", filename="opaque-large-source.md",
    )).document
    result = EvidenceCourseEngine().generate_from_document(source)
    assert result.evidence_plan
    assert all("opaque-large-source" not in lesson.title for lesson in result.evidence_plan)
    assert all("Лимит" in lesson.title for lesson in result.evidence_plan)
    assert {fact.value for fact in result.admitted_facts} == {f"{i * 100} тенге" for i in range(1, 7)}
