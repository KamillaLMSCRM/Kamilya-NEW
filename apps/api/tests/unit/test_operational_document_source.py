"""Source-owned regulatory tables and readable realization, without client data."""
from __future__ import annotations

import json
import re

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import (
    _grounded_fallback,
    _narrative_fact_metadata,
    _split_narrative_chunk,
    build_evidence_source,
)
from app.modules.ai.evidence_engine.engine import admit_document_facts
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine, _readable_source_text
from app.modules.ai.ingestion import DocumentChunker, is_sentence_like_ordinal_heading


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


def test_long_regulatory_cell_keeps_category_with_its_own_limits() -> None:
    value = (
        "От 900 100 тенге и выше для филиалов северного региона; "
        "от 1 200 100 тенге и выше для филиалов южного региона."
    )
    fact = SourceFact(
        "limit-II", "II категория", "Лимит выдачи", value,
        "doc_id=synthetic;table=1;row=3;column=2",
    )
    lesson = LessonDraft("limits", "Правила", "Лимиты", "Проверить категорию", "", (fact.fact_id,), (), 3)
    rendered, _, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        {"blocks": [{"heading": "Лимит выдачи", "text": value, "fact_ids": [fact.fact_id]}]},
        base_lesson=lesson, plan_fact_ids={fact.fact_id}, facts_by_id={fact.fact_id: fact}, seeds=[],
    )
    assert "II категория — Лимит выдачи:" in rendered.content
    assert value in rendered.content
    assert blocks[0].fact_ids == (fact.fact_id,)


def test_markitdown_empty_header_and_split_formatted_rows_keep_real_rules() -> None:
    north = "для филиалов северного региона, включая города Северный, Речной и Озёрный"
    south = "для филиалов южного региона, включая города Южный, Степной и Горный"
    text = (
        "**УТВЕРЖДАЮ**\n\nГенеральный директор\n\n**Правила согласования**\n\n"
        "|  |  |\n| --- | --- |\n"
        "| **Категория** | **Лимит выдачи, тенге** |\n"
        f"| I категория | От 45**0 100 до 900 000** тенге {north}; "
        f"от **450 100 до 1 200 000** тенге {south}. |\n"
        f"| II категория | От **900 100** тенге **и выше** {north}; "
        f"от **1 200 100** тенге **и выше** {south}. |\n\n"
        "**2. Порядок согласования**\n\n"
        "Сотрудник обязан проверить подтверждение до выдачи."
    )
    bundle = build_evidence_source(_corpus(text))
    primary, _supporting, _ = admit_document_facts(bundle.document)
    limits = [fact for fact in primary if "table=" in fact.source_locator]
    assert {fact.subject for fact in limits} == {"I категория", "II категория"}
    assert len(limits) == 2
    assert "450 100 до 900 000" in limits[0].value
    assert "1 200 100" in limits[1].value
    assert all("**" not in fact.value and "**" not in fact.attribute for fact in limits)
    assert not any("УТВЕРЖДАЮ" in fact.value for fact in primary)
    assert any("до выдачи" in fact.value for fact in primary)


def test_operational_footnote_before_formatted_body_is_not_cover_metadata() -> None:
    text = (
        "**УТВЕРЖДАЮ**\n\nГенеральный директор\n\n**Правила выдачи**\n\n"
        "*Если общая сумма заявок одного клиента за один день превышает лимит, "
        "необходимо согласовать общую сумму до выдачи.*\n\n"
        "**2. Проверка документов**\n\nСотрудник обязан проверить документ клиента."
    )
    primary, supporting, _ = admit_document_facts(build_evidence_source(_corpus(text)).document)
    assert any("общая сумма заявок" in fact.value for fact in primary)
    assert not any("УТВЕРЖДАЮ" in fact.value for fact in primary)
    assert not any("общая сумма заявок" in fact.value for fact in supporting)


def test_complete_actor_definition_before_list_intro_is_not_discarded() -> None:
    text = (
        "**УТВЕРЖДАЮ**\n\n**Регламент проверки**\n\n"
        "Согласование заявок проводят начальники смен и старшие специалисты. "
        "В организации существуют две категории заявок:\n\n"
        "**2. Порядок работы**\n\nСотрудник обязан проверить подтверждение."
    )
    primary, _, _ = admit_document_facts(build_evidence_source(_corpus(text)).document)
    assert any("начальники смен и старшие специалисты." in fact.value for fact in primary)
    assert not any(fact.value.endswith(":") for fact in primary)


def test_docling_hierarchical_bullets_remain_separate_contextual_rules() -> None:
    text = (
        "# 1. ОБЩИЕ ТРЕБОВАНИЯ\n\n"
        "- 1.1. Сотрудник обязан проверить свободный доступ к выходу.\n"
        "- 1.2. Руководитель обязан:\n"
        "1. -назначить ответственного за помещение;\n"
        "2. -организовать проверку сигнализации.\n"
        "- 1.3. Работникам следует:\n"
        "- 1) сообщить о признаках дыма;\n"
        "- 2) прекратить использование неисправного прибора.\n"
        "- 1.4. Запрещено перекрывать запасной выход."
    )
    primary, _, _ = admit_document_facts(build_evidence_source(_corpus(text)).document)
    assert len(primary) == 4
    assert any("Руководитель обязан:" in fact.value and "-назначить" in fact.value for fact in primary)
    assert any("Работникам следует:" in fact.value and "сообщить о признаках дыма" in fact.value for fact in primary)
    assert any(fact.value.startswith("1.4.") for fact in primary)


def test_empty_table_header_does_not_guess_a_schema_from_an_ordinary_record() -> None:
    with pytest.raises(ValueError, match="evidence_source_table_header_unavailable"):
        build_evidence_source(_corpus(
            "|  |  |\n| --- | --- |\n| I категория | 900 тенге |\n| II категория | 1200 тенге |"
        ))


def test_actor_abbreviation_before_a_colon_does_not_become_a_complete_rule() -> None:
    primary, _, _ = admit_document_facts(build_evidence_source(_corpus(
        "**Правила работы**\n\nПроверку обязан выполнить специалист в г. Северном:\n\n"
        "**2. Основной порядок**\n\nСотрудник обязан проверить подтверждение."
    )).document)
    assert not any(fact.value.endswith("специалист в г.") for fact in primary)


@pytest.mark.parametrize("purpose", [
    "Цель документа: необходимо обеспечить единый порядок обработки заявок.",
    "Цель регламента — сотрудники должны понимать общий порядок работы.",
    "Назначение документа: определить, как проводят обработку всех входящих заявок сотрудников.",
    "Purpose: staff must understand the general processing approach.",
])
def test_cover_purpose_with_modal_verbs_remains_supporting(purpose: str) -> None:
    bundle = build_evidence_source(_corpus(
        "**УТВЕРЖДАЮ**\n\nГенеральный директор\n\n**материалы26**\n\n" + purpose + "\n\n"
        "**2. Основной порядок**\n\nСотрудник обязан проверить подтверждение."
    ))
    primary, _, _ = admit_document_facts(bundle.document)
    assert not any(purpose in fact.value for fact in primary)
    assert any(purpose in fact.value for section in bundle.document.sections
               if section.role == "supporting" for fact in section.facts)


def test_bold_nominal_section_after_colon_is_not_absorbed_into_the_rule() -> None:
    parts = _split_narrative_chunk(
        "Если сумма превышает лимит, необходимо согласовать заявку:\n\n"
        "**2. Порядок проверки**\n\nСотрудник обязан проверить документ."
    )
    assert parts == [
        "Если сумма превышает лимит, необходимо согласовать заявку:",
        "Сотрудник обязан проверить документ.",
    ]


def test_evacuation_route_heading_is_not_an_infinitive_action() -> None:
    text = (
        "# 2. СОДЕРЖАНИЕ ПОМЕЩЕНИЙ\n\nСотрудник обязан содержать помещение в чистоте.\n\n"
        "# 3. ПУТИ ЭВАКУАЦИИ\n\nВыход должен открываться изнутри без ключа."
    )
    primary, _, _ = admit_document_facts(build_evidence_source(_corpus(text)).document)
    exit_rule = next(fact for fact in primary if "без ключа" in fact.value)
    assert exit_rule.subject == "3. ПУТИ ЭВАКУАЦИИ"
    assert not is_sentence_like_ordinal_heading("4. Сети связи")
    assert is_sentence_like_ordinal_heading("5. Нести ответственность за учет документов")
    assert is_sentence_like_ordinal_heading("6. Пройти проверку документов")


def test_whole_lesson_fallback_keeps_row_identity_and_readable_paragraphs() -> None:
    value = (
        "Сотрудник обязан проверить документы до выдачи. "
        + "Проверка проводится в присутствии ответственного лица до подписания акта. " * 8
        + "Если есть расхождение, выдача запрещена."
    )
    fact = SourceFact("procedure-II", "II категория", "Порядок согласования", value,
                      "doc_id=synthetic;source_revision=v1;section=rules;table=2;row=3;column=2")
    lesson = LessonDraft("procedure", "Правила", "Согласование", "Применять порядок", "", (fact.fact_id,), (), 2)
    rendered, _, blocks = _grounded_fallback(
        base_lesson=lesson, plan_fact_ids=(fact.fact_id,), facts_by_id={fact.fact_id: fact}, seeds=[],
    )
    assert "II категория — Порядок согласования:" in rendered.content
    assert len(rendered.content.split("\n\n")) >= 4
    assert re.sub(r"\s+", "", value) in re.sub(r"\s+", "", blocks[0].text)
    assert blocks[0].fact_ids == (fact.fact_id,)
