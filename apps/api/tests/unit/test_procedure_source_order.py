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
