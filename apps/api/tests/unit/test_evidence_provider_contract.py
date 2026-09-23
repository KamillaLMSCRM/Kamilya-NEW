from __future__ import annotations

from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine
from app.modules.ai.evidence_engine.quality import is_generic_question


def _short_catalog_lesson():
    facts = {
        "material": SourceFact(
            fact_id="material", subject="Север", attribute="Материал фасада",
            value="МДФ", source_locator="sheet=Коллекции;row=3",
        ),
        "purpose": SourceFact(
            fact_id="purpose", subject="Север", attribute="Назначение",
            value="Для прихожей", source_locator="sheet=Коллекции;row=2",
        ),
    }
    lesson = LessonDraft(
        lesson_id="catalog-lesson", module_title="Север", title="Коллекция Север",
        objective="Различать характеристики", content="",
        fact_ids=("material", "purpose"), supporting_fact_ids=(), duration_minutes=2,
    )
    return facts, lesson


def test_realizer_drops_unsupported_advice_without_repeating_already_covered_short_facts() -> None:
    facts, base = _short_catalog_lesson()
    payload = {
        "title": base.title, "objective": base.objective,
        "blocks": [
            {"heading": "Подтверждённые характеристики",
             "text": "Материал фасада — МДФ. Назначение — для прихожей.",
             "fact_ids": ["material", "purpose"]},
            {"heading": "Как применять", "text": "Рекомендуйте клиенту быструю покупку.",
             "fact_ids": ["material", "purpose"]},
        ],
        "questions": [],
    }
    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids=set(base.fact_ids), facts_by_id=facts, seeds=[],
    )
    assert len(blocks) == 1
    assert "Как применять" not in lesson.content
    assert "МДФ Для прихожей" not in lesson.content


def test_realizer_replaces_only_unsupported_blocks_with_separate_labeled_facts() -> None:
    facts, base = _short_catalog_lesson()
    payload = {
        "title": base.title, "objective": base.objective,
        "blocks": [{"heading": "Советы", "text": "Рекомендуйте клиенту быструю покупку.",
                    "fact_ids": ["material", "purpose"]}],
        "questions": [],
    }
    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids=set(base.fact_ids), facts_by_id=facts, seeds=[],
    )
    assert len(blocks) == 2
    assert "### Материал фасада" in lesson.content
    assert "### Назначение" in lesson.content
    assert "МДФ Для прихожей" not in lesson.content


def test_catalog_fallback_keeps_subject_and_label_with_each_short_cell() -> None:
    facts = {
        "feature": SourceFact(
            fact_id="feature", subject="Берег", attribute="Особенность",
            value="Ящики полного выдвижения",
            source_locator="doc_id=synthetic;section=Коллекции;row=4;column=2",
        ),
        "material": SourceFact(
            fact_id="material", subject="Берег", attribute="Материал фасада",
            value="ЛДСП", source_locator="doc_id=synthetic;section=Коллекции;row=4;column=2",
        ),
    }
    base = LessonDraft(
        lesson_id="shore-lesson", module_title="Коллекции", title="Коллекция Берег",
        objective="Различать характеристики", content="", fact_ids=("feature", "material"),
        supporting_fact_ids=(), duration_minutes=2,
    )
    payload = {
        "blocks": [{"heading": "Совет", "text": "Убедите клиента купить быстрее.",
                    "fact_ids": ["feature", "material"]}],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids=set(facts), facts_by_id=facts, seeds=[],
    )

    assert len(blocks) == 2
    assert "Берег — Особенность: Ящики полного выдвижения." in lesson.content
    assert "Берег — Материал фасада: ЛДСП." in lesson.content


def test_later_block_cannot_repeat_a_rule_already_taught_in_full() -> None:
    fact = SourceFact(
        fact_id="unload-rule", subject="Приёмка", attribute="Правило",
        value=("Сотрудник сверяет номер накладной с номером заказа до разгрузки. "
               "Если номера не совпадают, разгрузку не начинают и сообщают "
               "руководителю смены."),
        source_locator="section=1;fact=1",
    )
    base = LessonDraft(
        lesson_id="unload-lesson", module_title="Приёмка", title="Проверка документов",
        objective="Применять правило", content="", fact_ids=(fact.fact_id,),
        supporting_fact_ids=(), duration_minutes=2,
    )
    payload = {
        "blocks": [
            {"heading": "Проверка до разгрузки", "text": fact.value,
             "fact_ids": [fact.fact_id]},
            {"heading": "Действия при несовпадении", "text":
             "Если номера накладной и заказа не совпадают, разгрузку не начинают.",
             "fact_ids": [fact.fact_id]},
        ],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact}, seeds=[],
    )

    assert len(blocks) == 1
    assert "сообщают руководителю смены" in lesson.content
    assert "### Действия при несовпадении" not in lesson.content


def test_spreadsheet_realizer_cannot_narrow_collection_to_a_supporting_item() -> None:
    short_facts, base = _short_catalog_lesson()
    facts = {
        fact_id: SourceFact(
            fact_id=fact.fact_id, subject=fact.subject, attribute=fact.attribute,
            value=fact.value,
            source_locator=f"doc_id=synthetic;section=Коллекции;row=4;column={index}",
        )
        for index, (fact_id, fact) in enumerate(short_facts.items(), start=2)
    }
    payload = {
        "title": "Комод «Север»: характеристики",
        "objective": "Объяснять покупателю свойства комода «Север».",
        "blocks": [{"heading": "Характеристики", "text":
                    "Материал фасада — МДФ. Назначение — для прихожей.",
                    "fact_ids": list(facts)}],
        "questions": [],
    }

    lesson, _questions, _blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids=set(facts), facts_by_id=facts, seeds=[],
    )

    assert lesson.title == base.title
    assert lesson.objective == base.objective


def test_spreadsheet_source_title_survives_invalid_model_title() -> None:
    fact = SourceFact(
        fact_id="material", subject="Север", attribute="Материал фасада",
        value="МДФ", source_locator="doc_id=synthetic;section=Коллекции;row=3;column=2",
    )
    base = LessonDraft(
        lesson_id="north", module_title="Коллекции", title="Север",
        objective="Различать подтверждённые свойства", content="",
        fact_ids=(fact.fact_id,), supporting_fact_ids=(), duration_minutes=2,
    )
    payload = {
        "title": "X" * 110,
        "blocks": [{"heading": "Материал", "text": "Материал фасада — МДФ.",
                    "fact_ids": [fact.fact_id]}],
        "questions": [],
    }

    lesson, _questions, _blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact}, seeds=[],
    )

    assert lesson.title == "Север"


def test_generic_fallback_heading_uses_source_words_not_internal_label() -> None:
    fact = SourceFact(
        fact_id="inspection", subject="Осмотр товара", attribute="положение",
        value="После сверки документов сотрудник осматривает упаковку.",
        source_locator="section=2;fact=1",
    )
    base = LessonDraft(
        lesson_id="inspection-lesson", module_title="Приёмка", title="Осмотр товара",
        objective="Знать порядок осмотра", content="", fact_ids=(fact.fact_id,),
        supporting_fact_ids=(), duration_minutes=2,
    )
    payload = {
        "title": base.title, "objective": base.objective,
        "blocks": [{"heading": "Советы", "text": "Покажите товар клиенту до приёмки.",
                    "fact_ids": [fact.fact_id]}], "questions": [],
    }
    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base, plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact}, seeds=[],
    )
    assert len(blocks) == 1
    assert blocks[0].heading == "После сверки документов сотрудник осматривает"
    assert "### положение" not in lesson.content
    assert fact.value in lesson.content


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


def test_realizer_removes_unsupported_advice_but_keeps_source_backed_teaching() -> None:
    fact = SourceFact(
        fact_id="fact-channel",
        subject="Защита данных",
        attribute="правило",
        value="Персональные данные передаются только по разрешённым каналам.",
        source_locator="section=privacy;fact=1",
    )
    base = LessonDraft(
        lesson_id="lesson-channel",
        module_title="Безопасность",
        title="Разрешённые каналы",
        objective="Применять правило разрешённых каналов.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{
            "heading": "Передача данных",
            "text": (
                "Персональные данные передаются только по разрешённым каналам. "
                "Если рабочий канал недоступен, нужно дождаться его восстановления "
                "или запросить разрешение руководителя."
            ),
            "fact_ids": [fact.fact_id],
        }],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert fact.value in lesson.content
    assert "дождаться" not in lesson.content.casefold()
    assert "разрешение руководителя" not in lesson.content.casefold()
    assert blocks[0].text == fact.value


def test_realizer_restores_omitted_sentence_from_a_cited_multi_sentence_fact() -> None:
    fact = SourceFact(
        fact_id="fact-channel-complete",
        subject="Защита данных",
        attribute="запрет",
        value=(
            "Персональные данные нельзя передавать в личные мессенджеры. "
            "Используется только разрешённый канал; срочность не является исключением."
        ),
        source_locator="section=privacy;part=1",
    )
    base = LessonDraft(
        lesson_id="lesson-channel-complete",
        module_title="Безопасность",
        title="Разрешённые каналы",
        objective="Применять полное правило разрешённых каналов.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{
            "heading": "Передача данных",
            "text": "Персональные данные нельзя передавать в личные мессенджеры.",
            "fact_ids": [fact.fact_id],
        }],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert "срочность не является исключением" in lesson.content
    assert blocks[0].text == fact.value


def test_realizer_deduplicates_identical_blocks_for_the_same_fact() -> None:
    fact = SourceFact(
        fact_id="fact-first-response",
        subject="Первый ответ",
        attribute="положение",
        value=(
            "Первый ответ подтверждает приём обращения и сообщает следующий шаг. "
            "Окончательное решение в первом ответе не требуется."
        ),
        source_locator="section=response;part=1",
    )
    base = LessonDraft(
        lesson_id="lesson-first-response",
        module_title="Обращения",
        title="Первый ответ",
        objective="Давать первый ответ.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [
            {"heading": "Определение", "text": fact.value, "fact_ids": [fact.fact_id]},
            {"heading": "Практика", "text": fact.value, "fact_ids": [fact.fact_id]},
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

    assert len(blocks) == 1
    assert lesson.content.count(fact.value) == 1


def test_realizer_does_not_append_single_sentence_after_supported_paraphrase() -> None:
    fact = SourceFact(
        fact_id="fact-rate",
        subject="Расчёт ставки",
        attribute="финансовое условие",
        value=(
            "1. Годовая эффективная ставка рассчитывается с учетом расходов Клиента, "
            "включающих вознаграждение, комиссионные и иные платежи Ломбарду за "
            "предоставление, обслуживание и погашение микрокредита."
        ),
        source_locator="section=rate;part=1",
    )
    base = LessonDraft(
        lesson_id="lesson-rate",
        module_title="Ставка",
        title="Расчёт эффективной ставки",
        objective="Учитывать расходы клиента.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    paraphrase = (
        "Годовая эффективная ставка учитывает расходы клиента: вознаграждение, "
        "комиссионные и другие платежи ломбарду за предоставление, обслуживание "
        "и погашение микрокредита."
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{"heading": "Учитываемые расходы", "text": paraphrase,
                    "fact_ids": [fact.fact_id]}],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert blocks[0].text == paraphrase
    assert fact.value not in lesson.content


def test_realizer_renders_an_exact_sentence_once_across_overlapping_facts() -> None:
    value = "Кроватей в линейке нет — кровать подбирают из совместимой коллекции."
    facts = {
        "fact-range": SourceFact(
            fact_id="fact-range",
            subject="Ассортимент",
            attribute="состав",
            value=value,
            source_locator="sheet=Коллекции;row=2;column=Состав",
        ),
        "fact-pitch": SourceFact(
            fact_id="fact-pitch",
            subject="Ассортимент",
            attribute="презентация",
            value=value,
            source_locator="sheet=Коллекции;row=2;column=Презентация",
        ),
    }
    base = LessonDraft(
        lesson_id="lesson-overlap",
        module_title="Коллекции",
        title="Ассортимент",
        objective="Учитывать состав линейки.",
        content="",
        fact_ids=tuple(facts),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [
            {"heading": "Состав", "text": value, "fact_ids": ["fact-range"]},
            {"heading": "Презентация", "text": value, "fact_ids": ["fact-pitch"]},
        ],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids=set(facts),
        facts_by_id=facts,
        seeds=[],
    )

    assert len(blocks) == 1
    assert lesson.content.count(value) == 1


def test_realizer_removes_a_short_semantic_repeat_but_keeps_both_fact_links() -> None:
    facts = {
        "fact-range": SourceFact(
            fact_id="fact-range",
            subject="Феникс",
            attribute="Особенности кроватей",
            value=(
                "Кроватей в линейке нет: для спальни шкафы Феникс комбинируют "
                "с кроватью другой линейки."
            ),
            source_locator="sheet=Коллекции;row=12;column=2",
        ),
        "fact-summary": SourceFact(
            fact_id="fact-summary",
            subject="Феникс",
            attribute="Для каких комнат",
            value="В коллекции Феникс кроватей нет.",
            source_locator="sheet=Коллекции;row=3;column=2",
        ),
    }
    base = LessonDraft(
        lesson_id="lesson-phoenix",
        module_title="Коллекции",
        title="Феникс",
        objective="Учитывать состав коллекции.",
        content="",
        fact_ids=tuple(facts),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{
            "heading": "Ассортимент",
            "text": facts["fact-range"].value + " " + facts["fact-summary"].value,
            "fact_ids": list(facts),
        }],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids=set(facts),
        facts_by_id=facts,
        seeds=[],
    )

    assert facts["fact-range"].value in lesson.content
    assert facts["fact-summary"].value not in lesson.content
    assert set(blocks[0].fact_ids) == set(facts)


def test_realizer_recognizes_an_inflected_short_repeat() -> None:
    fact = SourceFact(
        fact_id="fact-style",
        subject="Феникс",
        attribute="Стиль",
        value=(
            "Коллекция выдержана в современном минимализме с нейтральной "
            "палитрой. Современный минимализм, нейтральная палитра."
        ),
        source_locator="sheet=Коллекции;row=4;column=2",
    )
    base = LessonDraft(
        lesson_id="lesson-style",
        module_title="Коллекции",
        title="Стиль Феникс",
        objective="Описывать стиль коллекции.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{
            "heading": "Стиль",
            "text": fact.value,
            "fact_ids": [fact.fact_id],
        }],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert "Коллекция выдержана" in lesson.content
    assert lesson.content.count("Современный минимализм") == 0
    assert len(blocks) == 1


def test_realizer_recognizes_a_catalog_list_repeat_with_inflected_items() -> None:
    detailed = (
        "Шкафы представлены сериями на 1/2/3 двери, угловыми, антресолями, "
        "комплектами полок и ящиков; внутри — металлическая штанга."
    )
    repeated = (
        "Серии 1 / 2 / 3 двери, угловые, антресоли, комплекты полок и ящиков."
    )
    fact = SourceFact(
        fact_id="fact-cabinets",
        subject="Феникс",
        attribute="Особенности шкафов",
        value=f"{detailed} {repeated}",
        source_locator="sheet=Коллекции;row=11;column=2",
    )
    base = LessonDraft(
        lesson_id="lesson-cabinets",
        module_title="Коллекции",
        title="Шкафы Феникс",
        objective="Описывать состав шкафов.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{
            "heading": "Шкафы",
            "text": fact.value,
            "fact_ids": [fact.fact_id],
        }],
        "questions": [],
    }

    lesson, _questions, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert detailed in lesson.content
    assert repeated not in lesson.content
    assert len(blocks) == 1


def test_realizer_removes_a_short_repeat_with_one_case_ending_difference() -> None:
    detailed = (
        "Кровати имеют основание на гибких ламелях; спокойный цвет создаёт "
        "мягкую зону сна в той же палитре, что шкаф и комод."
    )
    repeated = "Спокойный цвет — мягкая зона сна в той же палитре, что шкаф и комод."
    fact = SourceFact(
        fact_id="fact-bed",
        subject="Чикаго Нео",
        attribute="Особенности кроватей",
        value=f"{detailed} {repeated}",
        source_locator="sheet=Коллекции;row=12;column=3",
    )
    base = LessonDraft(
        lesson_id="lesson-bed",
        module_title="Коллекции",
        title="Кровати Чикаго Нео",
        objective="Описывать особенности кроватей.",
        content="",
        fact_ids=(fact.fact_id,),
        supporting_fact_ids=(),
        duration_minutes=2,
    )
    payload = {
        "title": base.title,
        "objective": base.objective,
        "blocks": [{
            "heading": "Кровати",
            "text": fact.value,
            "fact_ids": [fact.fact_id],
        }],
        "questions": [],
    }

    lesson, _questions, _blocks = ProviderBackedEvidenceEngine._validate_and_render(
        payload,
        base_lesson=base,
        plan_fact_ids={fact.fact_id},
        facts_by_id={fact.fact_id: fact},
        seeds=[],
    )

    assert detailed in lesson.content
    assert repeated not in lesson.content


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
