from __future__ import annotations

from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine
from app.modules.ai.evidence_engine.quality import is_generic_question


def test_realizer_preserves_valid_provider_content_and_fills_omitted_facts() -> None:
    facts = {
        "fact-1": SourceFact(
            fact_id="fact-1",
            subject="Приемка",
            attribute="действие",
            value="Сотрудник сверяет номер поставки.",
            source_locator="section=1;fact=1",
        ),
        "fact-2": SourceFact(
            fact_id="fact-2",
            subject="Приемка",
            attribute="запрет",
            value="Поставки не смешивают до завершения приемки.",
            source_locator="section=1;fact=2",
        ),
    }
    base = LessonDraft(
        lesson_id="lesson-1",
        module_title="Приемка",
        title="Подготовка к приемке",
        objective="Применять правила приемки.",
        content="",
        fact_ids=("fact-1", "fact-2"),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": "Подготовка к приемке",
        "objective": "Применять правила приемки.",
        "blocks": [
            {
                "heading": "Проверка поставки",
                "text": "Перед приемкой сотрудник сверяет номер поставки.",
                "fact_ids": ["fact-1"],
            }
        ],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids=set(base.fact_ids),
        facts_by_id=facts,
        seeds=[],
    )

    assert [block.fact_ids for block in blocks] == [("fact-1",), ("fact-2",)]
    assert "Перед приемкой сотрудник сверяет номер поставки." in lesson.content
    assert "Поставки не смешивают до завершения приемки." in lesson.content


def test_section_membership_question_is_generic() -> None:
    assert is_generic_question(
        "Какое утверждение относится к разделу «Назначение и область применения»?"
    )
    assert is_generic_question(
        "Какое правило относится к разделу «Зонирование и адресное хранение»?"
    )


def test_realizer_cannot_change_the_attribute_of_a_specific_seed_question() -> None:
    fact = SourceFact(
        fact_id="fact-width",
        subject="АЛ-НШ-300",
        attribute="ширина",
        value="Ширина модуля составляет 300 мм.",
        source_locator="sheet=Модули;row=2",
    )
    base = LessonDraft(
        lesson_id="lesson-width",
        module_title="Модули",
        title="Размеры модулей",
        objective="Выбирать модуль по размеру.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    seed = QuestionDraft(
        question_id="question-width",
        lesson_id=base.lesson_id,
        kind="single_choice",
        prompt="Какая ширина у модуля АЛ-НШ-300?",
        options=("300", "400", "500"),
        correct_answer="300",
        explanation="Ширина модуля составляет 300 мм.",
        fact_id=fact.fact_id,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [
            {
                "heading": "Ширина модуля",
                "text": fact.value,
                "fact_ids": [fact.fact_id],
            }
        ],
        "questions": [
            {
                "prompt": "Какой код модуля соответствует запросу?",
                "explanation": fact.value,
                "fact_ids": [fact.fact_id],
            }
        ],
    }

    _lesson, questions, _blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[seed],
    )

    assert questions[0].prompt == seed.prompt


def test_realizer_neutralizes_blocked_sales_comparisons_copied_from_source() -> None:
    fact = SourceFact(
        fact_id="fact-positioning",
        subject="Чикаго Нео",
        attribute="Основная идея",
        value=(
            "Дорогая матовая эстетика и полноценные габариты, "
            "а не компакт с маркетплейса."
        ),
        source_locator="sheet=Коллекции;row=4",
    )
    base = LessonDraft(
        lesson_id="lesson-positioning",
        module_title="Коллекции",
        title="Чикаго Нео",
        objective="Объяснять позиционирование коллекции.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [
            {
                "heading": "Позиционирование",
                "text": fact.value,
                "fact_ids": [fact.fact_id],
            }
        ],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert "маркетплейс" not in lesson.content.casefold()
    assert "дорогая матовая эстетика и полноценные габариты" in lesson.content.casefold()
    assert blocks[0].text in lesson.content
