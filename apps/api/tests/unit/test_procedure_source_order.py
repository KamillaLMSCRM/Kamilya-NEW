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


def test_nonadjacent_source_owned_blocks_with_same_heading_keep_source_order():
    locator = "doc_id=d;source_revision=r;section=electrical;part={}"
    facts = [
        SourceFact("f1", "Electrical rules", "rule", "4.1. Follow the installation standard.",
                   locator.format(1)),
        SourceFact("f2", "Electrical rules", "rule", "4.2. Responsible workers must:\n- inspect equipment;",
                   locator.format(2)),
        SourceFact("f3", "Electrical rules", "rule", "4.3. Equipment must have circuit protection.",
                   locator.format(3)),
        SourceFact("f4", "Electrical rules", "rule", "4.4. Equipment must be de-energized after work.",
                   locator.format(4)),
        SourceFact("f5", "Electrical rules", "rule", "4.5. During operation it is prohibited:\n- use damaged equipment;",
                   locator.format(5)),
        SourceFact("f6", "Electrical rules", "rule", "4.6. Repair dangerous defects immediately.",
                   locator.format(6)),
    ]
    payload = {
        "title": "Electrical rules",
        "objective": "Apply electrical rules",
        "blocks": [
            {"heading": "Installation", "text": facts[0].value, "fact_ids": ["f1"]},
            {
                "heading": "Electrical rules",
                "text": f"{facts[1].value}\n{facts[4].value}",
                "fact_ids": ["f2", "f5"],
            },
            {
                "heading": "Protection and shutdown",
                "text": f"{facts[2].value} {facts[3].value}",
                "fact_ids": ["f3", "f4"],
            },
            {"heading": "Repair", "text": facts[5].value, "fact_ids": ["f6"]},
        ],
        "questions": [],
    }

    lesson, _, _ = render(facts, payload)

    assert [lesson.content.index(f"4.{part}.") for part in range(1, 7)] == sorted(
        lesson.content.index(f"4.{part}.") for part in range(1, 7)
    )


def test_provider_block_cannot_move_nonadjacent_plain_rules_before_intervening_rule():
    locator = "doc_id=d;source_revision=r;section=electrical;part={}"
    facts = [
        SourceFact("z-install", "Electrical rules", "rule",
                   "Install each unit under the verified standard.", locator.format(1)),
        SourceFact("m-inspect", "Electrical rules", "rule",
                   "Responsible workers inspect each unit on schedule.", locator.format(2)),
        SourceFact("a-protect", "Electrical rules", "rule",
                   "Every unit has circuit protection.", locator.format(3)),
        SourceFact("x-shutdown", "Electrical rules", "rule",
                   "De-energize each unit after work.", locator.format(4)),
        SourceFact("b-prohibit", "Electrical rules", "rule",
                   "Do not use a damaged unit.", locator.format(5)),
    ]
    payload = {
        "title": "Electrical rules",
        "objective": "Apply electrical rules",
        "blocks": [
            {
                "heading": "Installation and protection",
                "text": (
                    "Install each unit according to the verified standard. "
                    "Every unit must have circuit protection."
                ),
                "fact_ids": ["z-install", "a-protect"],
            },
            {"heading": "Inspection", "text": facts[1].value, "fact_ids": ["m-inspect"]},
            {"heading": "Shutdown", "text": facts[3].value, "fact_ids": ["x-shutdown"]},
            {"heading": "Prohibition", "text": facts[4].value, "fact_ids": ["b-prohibit"]},
        ],
        "questions": [],
    }

    lesson, _, blocks = render(facts, payload)

    assert [lesson.content.index(fact.value) for fact in facts] == sorted(
        lesson.content.index(fact.value) for fact in facts
    )
    assert [block.fact_ids for block in blocks[:3]] == [
        ("z-install",), ("m-inspect",), ("a-protect",),
    ]
    assert [blocks[0].text, blocks[2].text] == [facts[0].value, facts[2].value]


def test_provider_block_keeps_adjacent_plain_rules_and_authored_heading():
    facts = [
        SourceFact("first", "Checks", "rule", "First verify the alarm.",
                   "doc_id=d;source_revision=r;section=checks;part=1"),
        SourceFact("second", "Checks", "rule", "Then verify the exit.",
                   "doc_id=d;source_revision=r;section=checks;part=2"),
    ]
    payload = {
        "title": "Checks",
        "objective": "Perform checks",
        "blocks": [{
            "heading": "Daily sequence",
            "text": f"{facts[0].value} {facts[1].value}",
            "fact_ids": ["first", "second"],
        }],
        "questions": [],
    }

    lesson, _, blocks = render(facts, payload)

    assert len(blocks) == 1
    assert blocks[0].heading == "Daily sequence"
    assert blocks[0].text == payload["blocks"][0]["text"]
    assert "### Daily sequence" in lesson.content


def test_adjacent_prose_blocks_with_same_heading_still_coalesce():
    facts = [
        SourceFact("f1", "Checks", "rule", "First verify the alarm.",
                   "doc_id=d;source_revision=r;section=checks;part=1"),
        SourceFact("f2", "Checks", "rule", "Then verify the exit.",
                   "doc_id=d;source_revision=r;section=checks;part=2"),
    ]
    payload = {
        "title": "Checks",
        "objective": "Perform checks",
        "blocks": [
            {"heading": "Daily checks", "text": facts[0].value, "fact_ids": ["f1"]},
            {"heading": "Daily checks", "text": facts[1].value, "fact_ids": ["f2"]},
        ],
        "questions": [],
    }

    lesson, _, blocks = render(facts, payload)

    assert len(blocks) == 1
    assert blocks[0].fact_ids == ("f1", "f2")
    assert lesson.content.count("### Daily checks") == 1


def test_provider_paraphrase_cannot_invent_object_for_unresolved_source_inspection():
    fact = SourceFact(
        "f1",
        "End-of-shift rules",
        "rule",
        (
            "7.3. At the end of a shift, each worker must put the workplace in order. "
            "The worker must de-energize all devices and inspect for signs of overheating. "
            "The last worker must close the windows and switch off the light."
        ),
        "doc_id=d;source_revision=r;section=closing;part=3",
    )
    payload = {
        "title": "End-of-shift rules",
        "objective": "Close the workplace safely",
        "blocks": [{
            "heading": "Workplace checks",
            "text": (
                "At the end of a shift, each worker must put the workplace in order, "
                "de-energize all devices and inspect them for signs of overheating. "
                "The last worker must close the windows and switch off the light."
            ),
            "fact_ids": ["f1"],
        }],
        "questions": [],
    }

    lesson, _, _ = render([fact], payload)

    assert "inspect them for signs" not in lesson.content
    assert "inspect for signs of overheating" in lesson.content
    assert "7.3." not in lesson.content


def test_captured_russian_inspection_shape_keeps_the_source_referent_unresolved():
    fact = SourceFact(
        "f1",
        "Требования по окончании работы",
        "положение",
        (
            "6.3. По окончании рабочего дня каждый сотрудник обязан проверить и привести "
            "в порядок своё рабочее место. Необходимо обесточить все электроприборы и "
            "осмотреть на наличие признаков возгорания. Уходящий последним из помещения "
            "должен проверить, закрыты ли форточки и окна, выключить свет."
        ),
        "doc_id=d;source_revision=r;section=closing;part=3",
    )
    payload = {
        "title": "Безопасность по окончании работы",
        "objective": "Безопасно завершать рабочий день",
        "blocks": [{
            "heading": "Порядок на рабочем месте",
            "text": (
                "По окончании рабочего дня каждый сотрудник обязан проверить и привести "
                "в порядок своё рабочее место, обесточить все электроприборы и осмотреть "
                "их на наличие признаков возгорания. Сотрудник, уходящий последним, "
                "проверяет, закрыты ли форточки и окна, и выключает свет."
            ),
            "fact_ids": ["f1"],
        }],
        "questions": [],
    }

    lesson, _, _ = render([fact], payload)

    assert "осмотреть их на наличие" not in lesson.content
    assert "осмотреть на наличие признаков возгорания" in lesson.content
    assert "6.3." not in lesson.content


def test_provider_keeps_object_referent_when_the_source_states_it_explicitly():
    fact = SourceFact(
        "f1",
        "Проверка оборудования",
        "положение",
        "Сотрудник должен отключить приборы и осмотреть их на наличие повреждений.",
        "doc_id=d;source_revision=r;section=inspection;part=1",
    )
    payload = {
        "title": "Проверка оборудования",
        "objective": "Проверять оборудование",
        "blocks": [{
            "heading": "Осмотр",
            "text": fact.value,
            "fact_ids": ["f1"],
        }],
        "questions": [],
    }

    lesson, _, _ = render([fact], payload)

    assert "осмотреть их на наличие повреждений" in lesson.content
