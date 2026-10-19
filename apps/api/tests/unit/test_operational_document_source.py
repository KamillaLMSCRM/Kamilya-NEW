"""Source-owned regulatory tables and readable realization, without client data."""
from __future__ import annotations

import json
import re

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import _narrative_fact_metadata, build_evidence_source
from app.modules.ai.evidence_engine.engine import admit_document_facts
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine, _readable_source_text
from app.modules.ai.ingestion import DocumentChunker


def _corpus(text: str) -> DirectSourceCorpus:
    rows = DocumentChunker(chunk_size=240, chunk_overlap=40).chunk_markdown(
        text, "synthetic-rules", "rules.docx",
    )
    chunks = tuple(DirectSourceChunk(
        chunk_id=f"synthetic-rules:{index}", doc_id="synthetic-rules", doc_name="rules.docx",
        title="материалы26", headings=tuple(json.loads(row["metadata"]["headings"])),
        text=row["text"], source_revision="document:synthetic-rules-v1", chunk_index=index,
    ) for index, row in enumerate(rows))
    return DirectSourceCorpus(
        tenant_id="synthetic-only", documents=(DirectSourceDocument(
            doc_id="synthetic-rules", title="материалы26", filename="rules.docx",
            category="training_material", source_revision="document:synthetic-rules-v1", chunks=chunks,
        ),), total_chars=len(text), total_chunks=len(chunks),
    )


def test_operational_limit_table_before_first_body_heading_is_not_supporting_cover() -> None:
    text = (
        "УТВЕРЖДАЮ\n\nГенеральный директор\n\nматериалы26\n\n"
        "| Категория | Лимит выдачи, тенге |\n| --- | --- |\n"
        "| I категория | От 450 100 до 900 000 тенге. |\n"
        "| II категория | От 900 100 тенге и выше. |\n\n"
        "2. Порядок согласования\n\nСотрудник обязан согласовать выдачу до передачи денег."
    )
    bundle = build_evidence_source(_corpus(text))
    primary, _supporting, _ = admit_document_facts(bundle.document)
    assert any("450 100" in fact.value for fact in primary)
    assert any("900 100" in fact.value for fact in primary)
    assert all("table=" in fact.source_locator for fact in primary if "900 100" in fact.value)


def test_explicit_reference_appendix_is_not_promoted_by_a_limit_column() -> None:
    text = (
        "# 1. Порядок работы\n\nСотрудник обязан проверить документ.\n\n"
        "# Приложение 1. Справочный каталог\n\n"
        "| Артикул | Лимит хранения |\n| --- | --- |\n| SKU-001 | 700 единиц. |"
    )
    primary, supporting, _ = admit_document_facts(build_evidence_source(_corpus(text)).document)
    assert not any("700 единиц" in fact.value for fact in primary)
    assert any("700 единиц" in fact.value for fact in supporting)


def test_document_metadata_table_is_not_an_operational_deadline() -> None:
    text = (
        "УТВЕРЖДАЮ\n\nГенеральный директор\n\nматериалы26\n\n"
        "| Документ | Срок действия документа | Владелец документа |\n"
        "| --- | --- | --- |\n| Положение | 31.12.2030 | Служба документации |\n\n"
        "# 2. Порядок работы\n\nСотрудник обязан проверить документ клиента до выдачи."
    )
    primary, supporting, _ = admit_document_facts(build_evidence_source(_corpus(text)).document)
    assert not any("31.12.2030" in fact.value for fact in primary)
    assert any("31.12.2030" in fact.value for fact in supporting)


def test_toc_label_and_signature_are_traceable_but_not_teachable_facts() -> None:
    for value in ("1. Общие положения.", "УТВЕРЖДАЮ", "Генеральный директор"):
        assert _narrative_fact_metadata(value)["confidence"] == 0.0
    assert _narrative_fact_metadata("Генеральный директор обязан назначить ответственного.")["confidence"] == 1.0


def test_realization_formats_source_bound_inline_rules_as_readable_blocks() -> None:
    text = (
        "После работы сотрудник обязан: - отключить электроприборы; "
        "- проверить сигнализацию; - убедиться в свободном доступе к выходу; "
        "- закрыть окна; - выключить освещение; - закрыть дверь. "
        "Дежурное освещение не отключают."
    )
    fact = SourceFact("fact-list", "Завершение работы", "обязанность", text, "section=6;part=1")
    lesson = LessonDraft("lesson-list", "Безопасность", "Завершение работы", "Выполнить проверку", "", (fact.fact_id,), (), 3)
    rendered, _, _ = ProviderBackedEvidenceEngine._validate_and_render(
        {"blocks": [{"heading": "Проверка помещения", "text": text, "fact_ids": [fact.fact_id]}]},
        base_lesson=lesson, plan_fact_ids={fact.fact_id}, facts_by_id={fact.fact_id: fact}, seeds=[],
    )
    assert len(re.findall(r"(?m)^- ", rendered.content)) >= 6
    assert "Дежурное освещение не отключают." in rendered.content
    assert rendered.fact_ids == (fact.fact_id,)
    # Layout cannot drop/reword the source facts or change answer evidence.
    assert re.sub(r"\s+", " ", rendered.content.split("\n\n", 1)[1]).strip() == text


def test_display_layout_preserves_negative_amounts_conditions_and_abbreviations() -> None:
    text = (
        "Сотрудник обязан проверить сумму -5 тенге и значение -10 до подтверждения. "
        + "Проверка выполняется в присутствии ответственного лица. " * 7
        + "См. стр. Иванов указан в примере. Рис. Образец сохраняется. "
        "Если тревога учебная, действуют по отдельному порядку, кроме аварийных случаев."
    )
    result = _readable_source_text(text)
    assert "-5 тенге" in result and "-10" in result
    assert "стр. Иванов" in result and "Рис. Образец" in result
    assert "кроме аварийных случаев" in result
    assert re.sub(r"\s+", "", result) == re.sub(r"\s+", "", text)
