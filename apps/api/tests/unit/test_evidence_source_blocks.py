from __future__ import annotations

from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import SourceDocument, SourceFact, SourceSection
from app.modules.ai.evidence_engine.source_blocks import split_narrative_blocks


def test_rule_and_exception_continuation_remain_one_lossless_block() -> None:
    text = (
        "Сотрудник проверяет документы до выдачи имущества.\n\n"
        "Исключение: при техническом сбое проверку завершают после восстановления системы."
    )

    assert split_narrative_blocks(text) == [
        "Сотрудник проверяет документы до выдачи имущества. "
        "Исключение: при техническом сбое проверку завершают после восстановления системы."
    ]


def test_list_introduction_remains_attached_to_its_bullets() -> None:
    text = "Перед началом сотрудник выполняет:\n\n- сверяет документы\n\n- фиксирует результат"

    assert split_narrative_blocks(text) == [
        "Перед началом сотрудник выполняет: - сверяет документы - фиксирует результат"
    ]


def test_numbered_and_lettered_lists_stay_with_their_introductions() -> None:
    text = (
        "Правило:\n1. первый пункт\n2. второй пункт\n\n"
        "Исключения:\nа) для технического сбоя\nб) для аварийного доступа\n\n"
        "3. Самостоятельная тема."
    )

    assert split_narrative_blocks(text) == [
        "Правило: 1. первый пункт 2. второй пункт",
        "Исключения: а) для технического сбоя б) для аварийного доступа",
        "3. Самостоятельная тема.",
    ]


def test_numbered_paragraphs_do_not_split_decimal_values_or_long_blocks() -> None:
    long_paragraph = " ".join(["Очень длинное правило сохраняется целиком."] * 40)
    text = f"1. Ставка составляет 2.5 процента.\n\n2. {long_paragraph}"

    assert split_narrative_blocks(text) == [
        "1. Ставка составляет 2.5 процента.",
        f"2. {long_paragraph}",
    ]


def test_independently_headed_tiny_topics_remain_separate_lessons() -> None:
    sections = tuple(
        SourceSection(
            section_id=f"section-{index}",
            title=title,
            role="primary",
            facts=(
                SourceFact(
                    fact_id=f"fact-{index}",
                    subject=title,
                    attribute="правило",
                    value=value,
                    source_locator=f"section={index}",
                ),
            ),
        )
        for index, (title, value) in enumerate(
            (
                ("1. Приемка", "Проверяйте накладную."),
                ("2. Хранение", "Закрывайте склад."),
            ),
            start=1,
        )
    )
    source = SourceDocument(
        source_id="tiny-topics",
        title="Правила склада",
        kind="narrative",
        sections=sections,
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    assert len(result.evidence_plan) == 2
    assert [len(lesson.fact_ids) for lesson in result.evidence_plan] == [1, 1]
    assert result.evidence_plan[0].fact_ids != result.evidence_plan[1].fact_ids


def test_single_paragraph_produces_one_lesson() -> None:
    source = SourceDocument(
        source_id="single-paragraph",
        title="Правило",
        kind="narrative",
        sections=(
            SourceSection(
                section_id="section",
                title="1. Правило",
                role="primary",
                facts=(
                    SourceFact(
                        fact_id="fact",
                        subject="Правило",
                        attribute="положение",
                        value="Сотрудник подтверждает выдачу подписью клиента.",
                        source_locator="section=1",
                    ),
                ),
            ),
        ),
    )

    assert len(EvidenceCourseEngine().generate_from_document(source).evidence_plan) == 1
