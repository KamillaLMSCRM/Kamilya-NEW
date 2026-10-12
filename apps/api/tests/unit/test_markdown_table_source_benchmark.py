"""Regression coverage for source-preserving ordinary Markdown tables."""

from __future__ import annotations

import json

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import build_evidence_source, generate_evidence_course
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.ingestion import DocumentChunker


def _corpus(markdown: str, *, doc_id: str = "matrix", filename: str = "matrix-04.md") -> DirectSourceCorpus:
    rows = DocumentChunker().chunk_markdown(markdown, doc_id, filename)
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"{doc_id}:chunk-{index}",
            doc_id=doc_id,
            doc_name=filename,
            title="Матрица пакетов",
            headings=tuple(json.loads(row["metadata"]["headings"])),
            text=row["text"],
            source_revision="revision-matrix-v1",
            chunk_index=index,
        )
        for index, row in enumerate(rows)
    )
    return DirectSourceCorpus(
        tenant_id="synthetic-table-benchmark",
        documents=(
            DirectSourceDocument(
                doc_id=doc_id,
                title="Матрица пакетов",
                filename=filename,
                category="training_material",
                source_revision="revision-matrix-v1",
                chunks=chunks,
            ),
        ),
        total_chars=len(markdown),
        total_chunks=len(chunks),
    )


def test_ordinary_markdown_table_preserves_rows_locators_and_adjacent_prose() -> None:
    markdown = (
        "# Матрица пакетов\n\n"
        "Перед выбором пакета проверьте активные учетные записи.\n\n"
        "| Пакет | Участники | Отчётность |\n"
        "|---|---:|---|\n"
        "| Старт | до 20 | итоговый статус |\n"
        "| Команда | до 80 | статус и прогресс |\n"
        "| Организация | до 300 | статус, прогресс и экспорт |\n\n"
        "После превышения лимита новые назначения приостанавливаются."
    )

    source = build_evidence_source(_corpus(markdown)).document
    facts = {fact.value: fact for section in source.sections for fact in section.facts}

    assert any("Перед выбором пакета" in value for value in facts)
    assert any("После превышения лимита" in value for value in facts)
    assert any("до 20" in value for value in facts)
    assert any("до 80" in value for value in facts)
    assert any("до 300" in value for value in facts)

    table_facts = [fact for fact in facts.values() if "до " in fact.value]
    assert table_facts
    for fact in table_facts:
        assert "doc_id=matrix" in fact.source_locator
        assert "source_revision=revision-matrix-v1" in fact.source_locator
        assert "chunk_ids=matrix:chunk-" in fact.source_locator
        assert "row=" in fact.source_locator
        assert "column=" in fact.source_locator


@pytest.mark.asyncio
async def test_mixed_valid_and_ragged_table_rejects_before_any_provider_call() -> None:
    markdown = (
        "# Примечания\n\n"
        "Текст | с разделителями | но без табличного заголовка.\n\n"
        "| Пакет | Участники | Отчётность |\n"
        "|---|---:|---|\n"
        "| Старт | до 20 | итоговый статус |\n"
        "| Неполная строка | до 10 |\n\n"
        "Продолжение описания после неполной строки."
    )

    class NoCallClient:
        async def __getattr__(self, _name: str):
            raise AssertionError("provider or embedding client was called")

    with pytest.raises(ValueError, match="evidence_source_malformed_markdown_table:ragged:chunk-0"):
        await generate_evidence_course(
            _corpus(markdown, doc_id="ragged"),
            intent=CourseIntent(),
            generation_client=NoCallClient(),
            embedding_client=NoCallClient(),
        )


def test_pipe_delimited_prose_remains_narrative() -> None:
    markdown = "# Примечания\n\nЦитата «Пакет | Участники | срок» приведена как обычный текст."

    source = build_evidence_source(_corpus(markdown, doc_id="pipe-prose")).document
    values = [fact.value for section in source.sections for fact in section.facts]

    assert any("Пакет | Участники | срок" in value for value in values)


def test_overlapping_duplicate_table_rows_are_emitted_once() -> None:
    table = (
        "| Пакет | Участники |\n"
        "|---|---:|\n"
        "| Старт | до 20 |"
    )
    source = build_evidence_source(
        _corpus(f"# Матрица пакетов\n\n{table}\n\n{table}", doc_id="overlap")
    ).document
    matching = [
        fact
        for section in source.sections
        for fact in section.facts
        if fact.value == "до 20" and "column=" in fact.source_locator
    ]
    assert len(matching) == 1


def test_multiple_tables_under_one_heading_keep_distinct_identity_and_values() -> None:
    markdown = (
        "# Матрица пакетов\n\n"
        "| Пакет | Участники |\n|---|---:|\n| Старт | до 20 |\n\n"
        "Вторая редакция ниже имеет тот же заголовок таблицы.\n\n"
        "| Пакет | Участники |\n|---|---:|\n| Старт | до 25 |"
    )
    source = build_evidence_source(
        _corpus(markdown, doc_id="two-tables")
    ).document
    matching = [
        fact
        for section in source.sections
        for fact in section.facts
        if fact.subject == "Старт" and fact.attribute == "Участники"
    ]

    assert {fact.value for fact in matching} == {"до 20", "до 25"}
    assert len({fact.fact_id for fact in matching}) == 2
    assert len({fact.source_locator for fact in matching}) == 2
    assert len({
        section.section_id
        for section in source.sections
        if section.title == "Матрица пакетов" and ":table:" in section.section_id
    }) == 2


def test_adjacent_tables_without_intervening_prose_preserve_both_values() -> None:
    markdown = (
        "# Матрица пакетов\n\n"
        "| Пакет | Участники |\n|---|---:|\n| Старт | до 20 |\n\n"
        "| Пакет | Участники |\n|---|---:|\n| Старт | до 25 |"
    )
    source = build_evidence_source(_corpus(markdown, doc_id="adjacent-tables")).document
    values = [fact.value for section in source.sections for fact in section.facts
              if fact.subject == "Старт" and fact.attribute == "Участники"]
    assert sorted(values) == ["до 20", "до 25"]


def test_converted_worksheet_table_keeps_existing_roles_and_locators() -> None:
    markdown = (
        "# [Worksheet] Коллекции\n\n"
        "| Коллекция | Материал |\n|---|---|\n| Базовая | МДФ |\n\n"
        "# [Worksheet] Номенклатура\n\n"
        "| Артикул | Наименование |\n|---|---|\n| N-001 | Шкаф |"
    )

    source = build_evidence_source(
        _corpus(markdown, doc_id="converted", filename="catalog.xlsx")
    ).document
    sections = {section.title: section for section in source.sections}

    assert "Коллекции" in sections
    assert "Номенклатура" in sections
    assert sections["Коллекции"].role == "primary"
    assert sections["Номенклатура"].role == "supporting"
    assert any("МДФ" in fact.value for fact in sections["Коллекции"].facts)
    assert any("Шкаф" in fact.value for fact in sections["Номенклатура"].facts)
