from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine


def render(facts, payload):
    lesson = LessonDraft("lesson", "Procedure", "Procedure", "Follow the procedure", "",
                         tuple(fact.fact_id for fact in facts), (), 1)
    return ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=lesson, plan_fact_ids=set(lesson.fact_ids),
        facts_by_id={fact.fact_id: fact for fact in facts}, seeds=[],
    )


def source_steps():
    # IDs deliberately sort in the reverse of the source order. A writer can
    # group step2 under step1; restoration must not place a later step first.
    return [
        SourceFact("z-first", "Проверка задания", "положение",
                   "1. Сотрудник загружает файл до 18:00 по времени организации.",
                   "doc_id=synthetic;source_revision=document:fixed;section=procedure;part=1"),
        SourceFact("a-second", "Проверка задания", "положение",
                   "2. При отсутствии результата сотрудник обращается к методисту. Электронная почта не заменяет загрузку файла.",
                   "doc_id=synthetic;source_revision=document:fixed;section=procedure;part=2"),
    ]


def mixed_writer(facts):
    return {"title": "Проверка задания", "objective": "Соблюдать порядок", "blocks": [{
        "heading": "Загрузка", "text": "Сотрудник загружает файл до 18:00 по времени организации. Электронная почта не заменяет загрузку файла.",
        "fact_ids": [fact.fact_id for fact in facts],
    }], "questions": []}


def test_restore_keeps_numbered_procedure_order_and_each_complete_step():
    facts = source_steps()
    lesson, _, blocks = render(facts, mixed_writer(facts))
    assert lesson.content.index("1. Сотрудник") < lesson.content.index("2. При отсутствии")
    assert [block.fact_ids for block in blocks] == [("z-first",), ("a-second",)]
    assert [block.text for block in blocks] == [fact.value for fact in facts]


@pytest.mark.parametrize("alter", ["different_document", "different_section", "noncontiguous", "nonprocedure"])
def test_unrelated_numbered_facts_are_not_blindly_reconstructed(alter):
    facts = source_steps()
    if alter == "different_document":
        facts[1] = replace(facts[1], source_locator=facts[1].source_locator.replace("doc_id=synthetic", "doc_id=other"))
    elif alter == "different_section":
        facts[1] = replace(facts[1], source_locator=facts[1].source_locator.replace("section=procedure", "section=other"))
    elif alter == "noncontiguous":
        facts[1] = replace(facts[1], value=facts[1].value.replace("2.", "4.", 1))
    else:
        facts = [replace(fact, value=fact.value[3:]) for fact in facts]
    _, _, blocks = render(facts, mixed_writer(facts))
    assert len(blocks) == 1
    assert blocks[0].heading == "Загрузка"


def test_mixed_writer_cannot_detach_table_cells_or_move_them_after_later_section():
    facts = [
        SourceFact("intro", "3. Классификация", "положение", "Сначала определяют уровень изменения.",
                   "doc_id=d;source_revision=r;section=classification;part=1"),
        SourceFact("z-cell", "Локальный", "Признак", "Одна группа, дата не меняется",
                   "doc_id=d;source_revision=r;section=classification;table=1;row=2;column=2"),
        SourceFact("a-cell", "Срочный", "Признак", "Риск срыва занятия в ближайшие 24 часа",
                   "doc_id=d;source_revision=r;section=classification;table=1;row=3;column=2"),
        SourceFact("later", "4. Проектирование", "положение", "После классификации инициатор готовит проект.",
                   "doc_id=d;source_revision=r;section=design;part=1"),
    ]
    payload = {"title": "Изменения", "objective": "Применять порядок", "blocks": [
        {"heading": "Проектирование", "text": facts[3].value, "fact_ids": ["later"]},
        {"heading": "Классификация", "text": facts[0].value, "fact_ids": ["intro", "a-cell", "z-cell"]},
    ], "questions": []}
    lesson, _, _ = render(facts, payload)
    assert "Локальный — Признак: Одна группа, дата не меняется." in lesson.content
    assert "Срочный — Признак: Риск срыва занятия в ближайшие 24 часа." in lesson.content
    assert lesson.content.index(facts[0].value) < lesson.content.index("Локальный —")
    assert lesson.content.index("Локальный —") < lesson.content.index("Срочный —")
    assert lesson.content.index("Срочный —") < lesson.content.index(facts[3].value)


@pytest.mark.parametrize("same_section", [False, True])
def test_two_tables_with_overlapping_rows_keep_source_table_order(same_section):
    facts = [
        SourceFact("a2", "Локальный", "Срок", "один день",
                   "doc_id=d;source_revision=r;section=classification;table=1;row=2;column=2"),
        SourceFact("a3", "Системный", "Срок", "три дня",
                   "doc_id=d;source_revision=r;section=classification;table=1;row=3;column=2"),
        SourceFact("b2", "Согласование", "Ответственный", "методист",
                   "doc_id=d;source_revision=r;section=approval;table=2;row=2;column=2"),
        SourceFact("b3", "Публикация", "Ответственный", "администратор",
                   "doc_id=d;source_revision=r;section=approval;table=2;row=3;column=2"),
    ]
    if same_section:
        facts[2:] = [replace(fact, attribute="Срок", source_locator=fact.source_locator.replace(
            "section=approval", "section=classification")) for fact in facts[2:]]
    lesson, _, blocks = render(facts, {"blocks": [{
        "heading": "Локальный", "text": "Локальный — Срок: один день.", "fact_ids": ["a2"],
    }], "questions": []})
    assert [fact_id for block in blocks for fact_id in block.fact_ids] == ["a2", "a3", "b2", "b3"]
    assert len(blocks) == 2
    assert lesson.content.index("Системный — Срок:") < lesson.content.index("Согласование —")
