from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import (
    _assessment_contract_reason_codes,
    _build_evidence_bank,
    _generate_tabular_assessment,
    _normalize_evidence_text,
    _validate_generated_question_set,
    _validate_question_evidence,
    capture_assessment_paths,
    generate_course_assessment,
    generate_lesson_assessment,
)
from app.modules.ai.assessment_schema import LessonAssessment
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


def _additional_questions() -> list[dict]:
    facts = [
        (
            "Когда передают график микрокредита?",
            "График микрокредита передают после подписания договора.",
            ["После подписания договора", "До подписания договора", "При обсуждении договора", "Без подписания договора"],
        ),
        (
            "Чем подтверждают погашение микрокредита?",
            "Погашение микрокредита подтверждают платёжной квитанцией.",
            [
                "Платёжной квитанцией",
                "Квитанцией плательщика",
                "Черновиком квитанции",
                "Неподписанной квитанцией",
            ],
        ),
        (
            "Где указывают срок микрокредита?",
            "Срок микрокредита указывают в подписанном договоре.",
            [
                "подписанном договоре",
                "предварительном договоре",
                "отменённом договоре",
                "неподписанном договоре",
            ],
        ),
        (
            "Когда фиксируют просрочку микрокредита?",
            "Просрочку микрокредита фиксируют после пропуска платежа.",
            ["После пропуска платежа", "До пропуска платежа", "При внесении платежа", "Без пропуска платежа"],
        ),
    ]
    return [
        {
            "question": prompt,
            "options": [{"text": text, "is_correct": i == 0} for i, text in enumerate(options)],
            "explanation": quote,
            "source_quote_id": f"E{index:02d}",
        }
        for index, (prompt, quote, options) in enumerate(facts, start=2)
    ]


@pytest.mark.parametrize(
    "question",
    [
        "Что именно разберём в этом уроке?",
        "Что включает обзор коллекций согласно заголовку?",
        "Что задано в таблице коллекций для каждой позиции?",
        "В каком виде ниже даны все шесть коллекций?",
        "Что описывает каждая строка в рабочей таблице «Коллекция»?",
        "Какие коллекции упоминаются в заголовке?",
        "Как в таблице коллекций описана каждая позиция?",
        "Какие коллекции разобраны ниже по этим признакам?",
        "Какие коллекции рассматриваются в разделе о стиле и материалах?",
        "Как называется коллекция, представленная в свидетельстве?",
        "Что представляет собой преимущество для клиента согласно уроку?",
        "Что рассматривается в теме о стилях и коллекциях?",
        "Что в этом уроке разбираем о каждой коллекции?",
    ],
)
def test_generation_contract_blocks_customer_reported_meta_question_pattern(
    question: str,
) -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": question,
                    "options": [
                        {"text": "как устроены вешалки прихожие гарнитуры и зеркала", "is_correct": True},
                        {"text": "как устроены вешалки прихожие гарнитуры и полки", "is_correct": False},
                        {"text": "как устроены вешалки прихожие гарнитуры и столы", "is_correct": False},
                        {"text": "как устроены вешалки прихожие гарнитуры и шкафы", "is_correct": False},
                    ],
                    "explanation": (
                        "В исходном материале указано: что именно разберём в этом уроке."
                    ),
                }
            ]
        },
        "ru",
    )

    assert issues
    assert any("malformed_question" in issue for issue in issues)


def test_generation_contract_blocks_choices_that_only_change_the_last_word() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Какие предметы входят в состав коллекции?",
                    "options": [
                        {
                            "text": "В коллекцию входят вешалки прихожие гарнитуры и зеркала",
                            "is_correct": True,
                        },
                        {
                            "text": "В коллекцию входят вешалки прихожие гарнитуры и полки",
                            "is_correct": False,
                        },
                        {
                            "text": "В коллекцию входят вешалки прихожие гарнитуры и столы",
                            "is_correct": False,
                        },
                        {
                            "text": "В коллекцию входят вешалки прихожие гарнитуры и шкафы",
                            "is_correct": False,
                        },
                    ],
                    "explanation": "Состав коллекции указан в исходном материале.",
                }
            ]
        },
        "ru",
    )

    assert any("low_information_distractors" in issue for issue in issues)


def test_generation_contract_blocks_short_choices_that_only_change_last_word() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Какие сведения даны для позиции?",
                    "options": [
                        {"text": "артикулы размеры и цены", "is_correct": True},
                        {"text": "артикулы размеры и скидки", "is_correct": False},
                        {"text": "артикулы размеры и бренды", "is_correct": False},
                        {"text": "артикулы размеры и адреса", "is_correct": False},
                    ],
                    "explanation": "Для позиции приведены артикул, размеры и цена.",
                }
            ]
        },
        "ru",
    )

    assert any("low_information_distractors" in issue for issue in issues)


def test_generation_contract_blocks_two_word_choices_with_shared_prefix() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Какое преимущество закреплено за коллекцией?",
                    "options": [
                        {"text": "светлые фасады", "is_correct": True},
                        {"text": "светлые ручки", "is_correct": False},
                        {"text": "светлые полки", "is_correct": False},
                        {"text": "светлые секции", "is_correct": False},
                    ],
                    "explanation": "Преимущество коллекции — светлые фасады.",
                }
            ]
        },
        "ru",
    )

    assert any("low_information_distractors" in issue for issue in issues)


def _source_with_additional_facts(source: str) -> str:
    return "\n".join([source, *(q["explanation"] for q in _additional_questions())])


def _loan_questions() -> list[dict]:
    facts = [
        ("approval", "application review", "application intake"),
        ("payment", "contract signing", "contract review"),
        ("closure", "final repayment", "partial repayment"),
        ("renewal", "credit reassessment", "credit application"),
        ("collection", "missed repayment", "scheduled repayment"),
    ]
    return [
        {
            "question": f"When does loan {subject} occur?",
            "options": [
                {"text": f"after {condition}", "is_correct": True},
                {"text": f"before {condition}", "is_correct": False},
                {"text": f"during {alternative}", "is_correct": False},
                {"text": f"without {condition}", "is_correct": False},
            ],
            "explanation": f"Loan {subject} occurs after {condition}.",
            "source_quote_id": f"E{index:02d}",
        }
        for index, (subject, condition, alternative) in enumerate(facts, start=1)
    ]


def test_fact_identity_normalizes_unicode_markdown_and_punctuation() -> None:
    assert _normalize_evidence_text("**Коллекция «Альфа» — ЛДСП.**") == (
        _normalize_evidence_text("Коллекция Альфа - ЛДСП")
    )


def _collection_table_source() -> str:
    return "\n".join(
        [
            "# [Worksheet] Коллекция",
            "",
            "| Коллекция | Стиль | Преимущество для клиента | Материал | Сценарий консультации |",
            "| --- | --- | --- | --- | --- |",
            "| Альфа | современный | модульная компоновка | ЛДСП | уточнить размеры помещения |",
            "| Бета | скандинавский | светлые фасады | МДФ | согласовать оттенок |",
            "| Гамма | лофт | усиленная фурнитура | металл и ЛДСП | обсудить нагрузку |",
            "| Дельта | минимализм | скрытые ручки | МДФ | показать механизм открывания |",
            "| Эпсилон | классический | вместительные секции | ЛДСП | уточнить объём хранения |",
            "| Зета | современный | регулируемые полки | ЛДСП | собрать требования к высоте |",
        ]
    )


def test_evidence_bank_excludes_markdown_table_header_row() -> None:
    bank = _build_evidence_bank(_collection_table_source())

    assert all("Преимущество для клиента" not in quote for quote in bank.values())
    assert any("Альфа" in quote for quote in bank.values())
    assert any("Зета" in quote for quote in bank.values())


def test_tabular_assessment_targets_lesson_column_without_reusing_prior_facts() -> None:
    source = _collection_table_source()
    evidence_bank = _build_evidence_bank(source)
    excluded = frozenset(
        {
            (
                _normalize_evidence_text(next(q for q in evidence_bank.values() if "Альфа" in q)),
                _normalize_evidence_text("уточнить размеры помещения"),
            ),
            (
                _normalize_evidence_text(next(q for q in evidence_bank.values() if "Бета" in q)),
                _normalize_evidence_text("согласовать оттенок"),
            ),
        }
    )

    result = _generate_tabular_assessment(
        evidence_bank=evidence_bank,
        bounded_source=source,
        lesson_title="Сценарии консультации по коллекциям",
        lesson_objectives=["Выбирать действие под запрос клиента"],
        language="ru",
        question_count=3,
        excluded_fact_keys=excluded,
    )

    assert result is not None
    assert len(result.mcq) == 3
    scenario_answers = {
        "обсудить нагрузку",
        "показать механизм открывания",
        "уточнить объём хранения",
        "собрать требования к высоте",
    }
    assert all(
        next(option.text for option in question.options if option.is_correct)
        in scenario_answers
        for question in result.mcq
    )
    assert all(len(question.options) == 4 for question in result.mcq)
    assert all(
        (
            _normalize_evidence_text(question.source_quote),
            _normalize_evidence_text(
                next(option.text for option in question.options if option.is_correct)
            ),
        )
        not in excluded
        for question in result.mcq
    )


def test_tabular_assessment_keeps_partial_target_facts_before_filling_other_columns() -> None:
    source = _collection_table_source()
    evidence_bank = _build_evidence_bank(source)
    excluded_answers = {
        "уточнить размеры помещения",
        "согласовать оттенок",
        "обсудить нагрузку",
    }
    excluded = frozenset(
        (
            _normalize_evidence_text(quote),
            _normalize_evidence_text(answer),
        )
        for quote in evidence_bank.values()
        for answer in excluded_answers
        if answer in quote
    )

    result = _generate_tabular_assessment(
        evidence_bank=evidence_bank,
        bounded_source=source,
        lesson_title="Практика: подбор сценария под запрос клиента",
        lesson_objectives=["Подбирать сценарий консультации"],
        language="ru",
        question_count=5,
        excluded_fact_keys=excluded,
    )

    assert result is not None
    correct_answers = {
        next(option.text for option in question.options if option.is_correct)
        for question in result.mcq
    }
    assert {
        "показать механизм открывания",
        "уточнить объём хранения",
        "собрать требования к высоте",
    } <= correct_answers
    assert len(result.mcq) == 5


def test_tabular_assessment_requires_four_distinct_peer_values() -> None:
    source = "\n".join(
        [
            "| Коллекция | Стиль |",
            "| --- | --- |",
            "| Альфа | современный |",
            "| Бета | скандинавский |",
            "| Гамма | лофт |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Стили коллекций",
        lesson_objectives=["Различать стиль каждой коллекции"],
        language="ru",
        question_count=3,
    )

    assert result is None


def test_tabular_assessment_maps_rendered_lesson_table_to_plain_source_rows() -> None:
    source = "\n".join(
        [
            "Альфа — современный — модульная компоновка — ЛДСП — уточнить размеры помещения",
            "Бета — скандинавский — светлые фасады — МДФ — согласовать оттенок",
            "Гамма — лофт — усиленная фурнитура — металл и ЛДСП — обсудить нагрузку",
            "Дельта — минимализм — скрытые ручки — МДФ — показать механизм открывания",
            "Эпсилон — классический — вместительные секции — ЛДСП — уточнить объём хранения",
            "Зета — современный — регулируемые полки — ЛДСП — собрать требования к высоте",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Сценарии консультации по коллекциям",
        lesson_objectives=["Выбирать действие под запрос клиента"],
        lesson_body=_collection_table_source(),
        language="ru",
        question_count=5,
    )

    assert result is not None
    assert len(result.mcq) == 5
    assert all(
        next(option.text for option in question.options if option.is_correct)
        in {
            "уточнить размеры помещения",
            "согласовать оттенок",
            "обсудить нагрузку",
            "показать механизм открывания",
            "уточнить объём хранения",
            "собрать требования к высоте",
        }
        for question in result.mcq
    )


def test_tabular_style_assessment_keeps_two_subjects_with_same_style() -> None:
    source = _collection_table_source()

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Стили коллекций",
        lesson_objectives=["Различать стилевые направления"],
        language="ru",
        question_count=6,
    )

    assert result is not None
    assert len(result.mcq) == 6
    assert all(
        len(next(option.text for option in question.options if option.is_correct).split()) == 1
        for question in result.mcq
    )
    assert sum(
        next(option.text for option in question.options if option.is_correct) == "современный"
        for question in result.mcq
    ) == 2


def test_partial_lesson_table_uses_full_source_only_for_peer_distractors() -> None:
    source = "\n".join(
        [
            "Альфа — современный — модульная компоновка — ЛДСП — уточнить размеры помещения",
            "Бета — скандинавский — светлые фасады — МДФ — согласовать оттенок",
            "Гамма — лофт — усиленная фурнитура — металл и ЛДСП — обсудить нагрузку",
            "Дельта — минимализм — скрытые ручки — МДФ — показать механизм открывания",
            "Эпсилон — классический — вместительные секции — ЛДСП — уточнить объём хранения",
            "Зета — современный — регулируемые полки — ЛДСП — собрать требования к высоте",
        ]
    )
    lesson_body = "\n".join(
        [
            "| Коллекция | Стиль |",
            "| --- | --- |",
            "| Альфа | современный |",
            "| Бета | скандинавский |",
            "| Гамма | лофт |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Стили коллекций Альфа, Бета и Гамма",
        lesson_objectives=["Различать стили трёх коллекций"],
        lesson_body=lesson_body,
        language="ru",
        question_count=3,
    )

    assert result is not None
    assert len(result.mcq) == 3
    assert all(
        any(subject in question.question for subject in {"Альфа", "Бета", "Гамма"})
        for question in result.mcq
    )
    assert all(
        option.text in {"современный", "скандинавский", "лофт", "минимализм", "классический"}
        for question in result.mcq
        for option in question.options
    )


def test_converter_spaced_source_table_keeps_lesson_subject_scope() -> None:
    source = "\n\n".join(
        [
            "# [Worksheet] Коллекция",
            "| Коллекция | Стиль | Преимущество для клиента | Материал | Сценарий консультации |",
            "| --- | --- | --- | --- | --- |",
            "| Альфа | современный | модульная компоновка | ЛДСП | уточнить размеры помещения |",
            "| Бета | скандинавский | светлые фасады | МДФ | согласовать оттенок |",
            "| Гамма | лофт | усиленная фурнитура | металл и ЛДСП | обсудить нагрузку |",
            "| Дельта | минимализм | скрытые ручки | МДФ | показать механизм открывания |",
            "| Эпсилон | классический | вместительные секции | ЛДСП | уточнить объём хранения |",
            "| Зета | современный | регулируемые полки | ЛДСП | собрать требования к высоте |",
        ]
    )
    lesson_body = "\n".join(
        [
            "| Коллекция | Стиль | Преимущество для клиента | Материал | Сценарий консультации |",
            "| --- | --- | --- | --- | --- |",
            "| Альфа | современный | модульная компоновка | ЛДСП | уточнить размеры помещения |",
            "| Бета | скандинавский | светлые фасады | МДФ | согласовать оттенок |",
            "| Гамма | лофт | усиленная фурнитура | металл и ЛДСП | обсудить нагрузку |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Коллекции Альфа, Бета и Гамма",
        lesson_objectives=["Сопоставлять характеристики трёх коллекций"],
        lesson_body=lesson_body,
        language="ru",
        question_count=5,
    )

    assert result is not None
    assert len(result.mcq) == 5
    assert all(
        any(subject in question.question for subject in {"Альфа", "Бета", "Гамма"})
        for question in result.mcq
    )
    assert all(
        option.text in source
        for question in result.mcq
        for option in question.options
    )


def test_vertical_collection_cards_map_attributes_to_source_columns() -> None:
    source = "\n\n".join(
        [
            "| Коллекция | Стиль | Преимущество для клиента | Материал | Сценарий консультации |",
            "| --- | --- | --- | --- | --- |",
            "| Альфа | современный | модульная компоновка | ЛДСП | уточнить размеры помещения |",
            "| Бета | скандинавский | светлые фасады | МДФ | согласовать оттенок |",
            "| Гамма | лофт | усиленная фурнитура | металл и ЛДСП | обсудить нагрузку |",
            "| Дельта | минимализм | скрытые ручки | МДФ | показать механизм открывания |",
            "| Эпсилон | классический | вместительные секции | ЛДСП | уточнить объём хранения |",
            "| Зета | современный | регулируемые полки | ЛДСП | собрать требования к высоте |",
        ]
    )
    lesson_body = "\n\n".join(
        [
            "## Альфа",
            "| Атрибут | Значение |",
            "| --- | --- |",
            "| Стиль | современный |",
            "| Преимущество для клиента | модульная компоновка |",
            "| Материал | ЛДСП |",
            "| Сценарий консультации | уточнить размеры помещения |",
            "",
            "## Бета",
            "| Параметр | Значение |",
            "| --- | --- |",
            "| Стиль | скандинавский |",
            "| Преимущество для клиента | светлые фасады |",
            "| Материал | МДФ |",
            "| Сценарий консультации | согласовать оттенок |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Коллекции Альфа и Бета",
        lesson_objectives=["Сопоставлять характеристики коллекций"],
        lesson_body=lesson_body,
        language="ru",
        question_count=5,
    )

    assert result is not None
    assert len(result.mcq) == 5
    assert all(
        "«Альфа»" in question.question or "«Бета»" in question.question
        for question in result.mcq
    )
    assert all(
        any(option.text in evidence for evidence in _build_evidence_bank(source).values())
        for question in result.mcq
        for option in question.options
    )


def test_unrelated_lesson_table_does_not_block_scoped_source_fallback() -> None:
    source = _collection_table_source()
    lesson_body = "\n".join(
        [
            "| Раздел | Примечание |",
            "| --- | --- |",
            "| Введение | Краткий обзор |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Коллекции Альфа и Бета",
        lesson_objectives=["Сопоставлять характеристики Альфы и Беты"],
        lesson_body=lesson_body,
        language="ru",
        question_count=5,
    )

    assert result is not None
    assert len(result.mcq) == 5
    assert all(
        "«Альфа»" in question.question or "«Бета»" in question.question
        for question in result.mcq
    )


def test_generic_scope_does_not_widen_source_table_fallback() -> None:
    source = _collection_table_source()

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Всесторонний обзор по коллекции",
        lesson_objectives=["Познакомиться с ассортиментом"],
        lesson_body="| Раздел | Примечание |\n| --- | --- |\n| Введение | Обзор |",
        language="ru",
        question_count=5,
    )

    assert result is None


def test_selected_collections_without_names_do_not_widen_source_fallback() -> None:
    source = _collection_table_source()

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Обзор выбранных коллекций",
        lesson_objectives=["Познакомиться с ассортиментом"],
        lesson_body="| Раздел | Примечание |\n| --- | --- |\n| Введение | Обзор |",
        language="ru",
        question_count=5,
    )

    assert result is None


def test_selected_collection_styles_without_names_do_not_mean_all_rows() -> None:
    source = _collection_table_source()

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Стили выбранных коллекций",
        lesson_objectives=["Сравнить выбранные позиции"],
        language="ru",
        question_count=5,
    )

    assert result is None


@pytest.mark.parametrize(
    "title",
    [
        "Не все коллекции",
        "Не каждая коллекция",
        "Not all collections",
        "Not every collection",
        "Not each collection",
    ],
)
def test_negated_all_scope_does_not_widen_source_fallback(title: str) -> None:
    source = _collection_table_source()

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title=title,
        lesson_objectives=["Познакомиться с ассортиментом"],
        language="ru",
        question_count=5,
    )

    assert result is None


def test_generic_one_word_answer_remains_an_incomplete_fragment() -> None:
    source = "Коллекция Альфа: при консультации уточнить размеры помещения."
    evidence_bank = {"E01": source}
    payload = {
        "mcq": [
            {
                "question": "Что требуется сотруднику при консультации по коллекции Альфа?",
                "options": [
                    {"text": "уточнить", "is_correct": True},
                    {"text": "размеры", "is_correct": False},
                    {"text": "помещения", "is_correct": False},
                    {"text": "коллекция", "is_correct": False},
                ],
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(
        payload,
        evidence_bank=evidence_bank,
        bounded_source=source,
        language="ru",
    )

    assert "MCQ #1: correct answer is an incomplete fragment" in issues


@pytest.mark.asyncio
async def test_compact_spreadsheet_assessment_uses_deterministic_table_path() -> None:
    class LLMShouldNotBeCalled:
        async def ainvoke(self, messages, config=None, response_format=None):
            raise AssertionError("structured table assessment must not call the model")

    result = await generate_lesson_assessment(
        LLMShouldNotBeCalled(),
        LessonContent(
            title="Сценарии консультации по коллекциям",
            objectives=["Выбирать действие под запрос клиента"],
            content="Generated prose is not evidence.",
            source_chunks=[_collection_table_source()],
            source_references=[],
        ),
        language="ru",
        compact=True,
    )

    assert len(result.mcq) == 3
    assert all(
        next(option.text for option in question.options if option.is_correct)
        in {
            "уточнить размеры помещения",
            "согласовать оттенок",
            "обсудить нагрузку",
            "показать механизм открывания",
            "уточнить объём хранения",
            "собрать требования к высоте",
        }
        for question in result.mcq
    )


@pytest.mark.asyncio
async def test_standard_course_uses_only_real_table_values_for_scoped_lessons() -> None:
    class LLMShouldNotBeCalled:
        async def ainvoke(self, messages, config=None, response_format=None):
            raise AssertionError("structured table assessment must not call the model")

    source = _collection_table_source()
    course = CourseContent(
        title="Консультация по коллекциям",
        modules=[
            ModuleContent(
                title="Коллекции",
                lessons=[
                    LessonContent(
                        title="Коллекции Альфа и Бета: стили и выгоды",
                        objectives=["Объяснять преимущества и сценарии консультации"],
                        content="Сравним коллекции Альфа и Бета.",
                        source_chunks=[source],
                        source_references=[],
                    ),
                    LessonContent(
                        title="Коллекции Гамма и Дельта: выбор для клиента",
                        objectives=["Различать стили и сценарии консультации"],
                        content="Сравним коллекции Гамма и Дельта.",
                        source_chunks=[source],
                        source_references=[],
                    ),
                    LessonContent(
                        title="Коллекции Эпсилон и Зета: особенности предложения",
                        objectives=["Называть преимущества и действия сотрудника"],
                        content="Сравним коллекции Эпсилон и Зета.",
                        source_chunks=[source],
                        source_references=[],
                    ),
                ],
            )
        ],
    )

    with capture_assessment_paths() as assessment_paths:
        result = await generate_course_assessment(
            LLMShouldNotBeCalled(),
            course,
            language="ru",
            compact=False,
        )

    source_values = {
        "современный",
        "скандинавский",
        "лофт",
        "минимализм",
        "классический",
        "модульная компоновка",
        "светлые фасады",
        "усиленная фурнитура",
        "скрытые ручки",
        "вместительные секции",
        "регулируемые полки",
        "уточнить размеры помещения",
        "согласовать оттенок",
        "обсудить нагрузку",
        "показать механизм открывания",
        "уточнить объём хранения",
        "собрать требования к высоте",
    }
    assert [len(assessment.mcq) for assessment in result.assessments] == [5, 5, 5]
    assert assessment_paths == ["tabular", "tabular", "tabular"]
    assert all(
        option.text in source_values
        for assessment in result.assessments
        for question in assessment.mcq
        for option in question.options
    )


@pytest.mark.asyncio
async def test_shared_collection_table_builds_three_distinct_lesson_assessments() -> None:
    class LLMShouldNotBeCalled:
        async def ainvoke(self, messages, config=None, response_format=None):
            raise AssertionError("structured table assessment must not call the model")

    source = _collection_table_source()
    course = CourseContent(
        title="Консультация по коллекциям",
        modules=[
            ModuleContent(
                title="Коллекции",
                lessons=[
                    LessonContent(
                        title="Стили коллекций",
                        objectives=["Различать стиль каждой коллекции"],
                        content="Generated prose is not evidence.",
                        source_chunks=[source],
                        source_references=[],
                    ),
                    LessonContent(
                        title="Преимущества коллекций для клиента",
                        objectives=["Называть преимущество каждой коллекции"],
                        content="Generated prose is not evidence.",
                        source_chunks=[source],
                        source_references=[],
                    ),
                    LessonContent(
                        title="Сценарии консультации по коллекциям",
                        objectives=["Выбирать действие под запрос клиента"],
                        content="Generated prose is not evidence.",
                        source_chunks=[source],
                        source_references=[],
                    ),
                ],
            )
        ],
    )

    result = await generate_course_assessment(
        LLMShouldNotBeCalled(),
        course,
        language="ru",
        compact=True,
    )

    assert [len(assessment.mcq) for assessment in result.assessments] == [3, 3, 3]
    fact_keys = [
        (
            _normalize_evidence_text(question.source_quote),
            _normalize_evidence_text(
                next(option.text for option in question.options if option.is_correct)
            ),
        )
        for assessment in result.assessments
        for question in assessment.mcq
    ]
    assert len(fact_keys) == len(set(fact_keys)) == 9


@pytest.mark.asyncio
async def test_three_whole_table_lessons_build_fifteen_distinct_questions() -> None:
    class LLMShouldNotBeCalled:
        async def ainvoke(self, messages, config=None, response_format=None):
            raise AssertionError("structured table assessment must not call the model")

    source = _collection_table_source()
    course = CourseContent(
        title="Коллекции и сценарии консультации",
        modules=[
            ModuleContent(
                title="Коллекции",
                lessons=[
                    LessonContent(
                        title="Обзор коллекций: стиль, преимущество и материал",
                        objectives=["Различать стили и преимущества коллекций"],
                        content=source,
                        source_chunks=[source],
                        source_references=[],
                    ),
                    LessonContent(
                        title="Сценарии консультации по коллекциям",
                        objectives=["Выбирать действие под запрос клиента"],
                        content=source,
                        source_chunks=[source],
                        source_references=[],
                    ),
                    LessonContent(
                        title="Практика: подбор сценария под запрос клиента",
                        objectives=["Подбирать сценарий консультации"],
                        content=source,
                        source_chunks=[source],
                        source_references=[],
                    ),
                ],
            )
        ],
    )

    with capture_assessment_paths() as assessment_paths:
        result = await generate_course_assessment(
            LLMShouldNotBeCalled(),
            course,
            language="ru",
            compact=False,
        )

    assert [len(assessment.mcq) for assessment in result.assessments] == [5, 5, 5]
    assert assessment_paths == ["tabular", "tabular", "tabular"]
    third_answers = {
        next(option.text for option in question.options if option.is_correct)
        for question in result.assessments[2].mcq
    }
    assert "собрать требования к высоте" in third_answers


def _questions(
    topic: str,
    fact: str,
    source_quote: str,
    count: int = 5,
    source_quote_id: str = "E01",
) -> list[dict]:
    fact_words = fact.split()
    distractors = [
        " ".join([*fact_words[:-1], "договора"]),
        " ".join(["оформления", *fact_words[1:]]),
        " ".join([fact_words[0], "подписания", *fact_words[2:]]),
    ]
    options = [
        {"text": fact, "is_correct": True},
        *[
            {"text": distractor, "is_correct": False}
            for distractor in distractors
        ],
    ]
    return [
        {
            "question": f"Что требуется для {topic}?",
            "options": options,
            "explanation": f"Материал связывает {topic} с {fact}.",
            "source_quote": source_quote,
            "source_quote_id": source_quote_id,
        }
    ] + _additional_questions()[:count - 1]


def test_contract_diagnostics_use_bounded_reason_codes():
    error = ValueError(
        "MCQ #1: unknown source evidence id; MCQ #2: correct answer is an incomplete fragment"
    )

    assert _assessment_contract_reason_codes(error) == (
        "evidence_reference,grounding,answer_quality,learner_text_quality"
    )


@pytest.mark.asyncio
async def test_standard_assessment_requests_five_mcq_questions_only():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            prompt = messages[-1]["content"]
            assert "Exactly 5 single choice questions" in prompt
            assert "Do not add true/false or matching questions" in prompt
            assert "ALLOWED_EVIDENCE_BANK" in prompt
            assert '"source_quote_id"' in prompt
            assert '"E01"' in prompt
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Выдача микрокредита выполняется после проверки заявления.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
            source_references=[],
        ),
        language="ru",
    )

    assert len(result.mcq) == 5
    assert result.mcq[0].source_quote.startswith("Выдача микрокредита")
    assert result.true_false == []
    assert result.matching == []


@pytest.mark.asyncio
async def test_generated_assessment_uses_original_source_chunks_as_evidence() -> None:
    source = _source_with_additional_facts(
        "Выдача микрокредита выполняется после проверки заявления."
    )
    generated_intro = (
        "В этом уроке разбираем правила. Эти правила — основа успешной работы."
    )

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            prompt = messages[-1]["content"]
            evidence_payload = prompt.split("ALLOWED_EVIDENCE_BANK", 1)[1].split(
                "END_ALLOWED_EVIDENCE_BANK", 1
            )[0]
            assert "Выдача микрокредита выполняется" in evidence_payload
            assert generated_intro not in evidence_payload
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Выдача микрокредита выполняется после проверки заявления.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=generated_intro,
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
    )

    assert len(result.mcq) == 5
    assert all("основа успешной работы" not in item.source_quote for item in result.mcq)


@pytest.mark.asyncio
async def test_assessment_prioritizes_shared_spreadsheet_rows_for_lesson_entities() -> None:
    source = "\n".join(
        [
            "Alpha approval occurs after application review.",
            "Alpha payment occurs after contract signing.",
            "Beta closure occurs after final repayment.",
            "Gamma renewal occurs after credit reassessment.",
        ]
    )
    questions = [
        {
            "question": prompt,
            "options": [
                {"text": correct, "is_correct": True},
                {"text": wrong[0], "is_correct": False},
                {"text": wrong[1], "is_correct": False},
                {"text": wrong[2], "is_correct": False},
            ],
            "explanation": quote,
            "source_quote_id": evidence_id,
        }
        for prompt, correct, wrong, quote, evidence_id in [
            (
                "When does Alpha approval occur?",
                "after application review",
                ("before application review", "during application intake", "without application review"),
                "Alpha approval occurs after application review.",
                "E01",
            ),
            (
                "When does Alpha payment occur?",
                "after contract signing",
                ("before contract signing", "during contract review", "without contract signing"),
                "Alpha payment occurs after contract signing.",
                "E02",
            ),
            (
                "When does Beta closure occur?",
                "after final repayment",
                ("before final repayment", "during partial repayment", "without final repayment"),
                "Beta closure occurs after final repayment.",
                "E03",
            ),
        ]
    ]

    class InspectingLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            prompt = messages[-1]["content"]
            evidence_section = prompt.split("ALLOWED_EVIDENCE_BANK", 1)[1].split(
                "END_ALLOWED_EVIDENCE_BANK", 1
            )[0]
            assert "Alpha" in evidence_section
            assert "Beta" in evidence_section
            assert "Gamma" in evidence_section
            preferred_section = prompt.split("PREFERRED_EVIDENCE_IDS", 1)[1].split(
                "END_PREFERRED_EVIDENCE_IDS", 1
            )[0]
            assert "E01" in preferred_section
            assert "E02" in preferred_section
            assert "E03" in preferred_section
            assert "E04" not in preferred_section
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {"mcq": questions, "true_false": [], "matching": []},
                    ensure_ascii=False,
                )
            )

    result = await generate_lesson_assessment(
        InspectingLLM(),
        LessonContent(
            title="Alpha and Beta collections",
            objectives=["Compare Alpha and Beta facts"],
            content="Generated prose is not evidence.",
            source_chunks=[source],
            source_references=[],
        ),
        language="en",
        compact=True,
    )

    assert len(result.mcq) == 3
    assert all("Gamma" not in question.source_quote for question in result.mcq)


@pytest.mark.asyncio
async def test_lesson_assessment_does_not_reuse_a_fact_from_an_earlier_lesson() -> None:
    questions = _questions(
        "выдачу микрокредита",
        "проверки заявления",
        "Выдача микрокредита выполняется после проверки заявления.",
    )
    source = _source_with_additional_facts(questions[0]["explanation"])
    excluded_fact = {
        (
            _normalize_evidence_text(questions[0]["explanation"]),
            _normalize_evidence_text(questions[0]["options"][0]["text"]),
        )
    }

    class RepeatingLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            prompt = messages[-1]["content"]
            assert "ALREADY_ASSESSED_FACTS" in prompt
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        RepeatingLLM(),
        LessonContent(
            title="Продолжение правил выдачи",
            content=source,
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
        excluded_fact_keys=excluded_fact,
    )

    assert len(result.mcq) == 4
    assert all(
        question.question != questions[0]["question"] for question in result.mcq
    )


@pytest.mark.asyncio
async def test_standard_assessment_retries_an_incomplete_result():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content='{"mcq": [], "true_false": [], "matching": []}'
                )
            retry_prompt = messages[-1]["content"]
            assert "Порядок рассмотрения заявления" in retry_prompt
            assert "Рассмотрение заявления начинается с проверки документов" in retry_prompt
            assert "base every question only on the authoritative source excerpts" in retry_prompt.lower()
            assert "Here is your output" not in retry_prompt
            assert '"source_quote_id"' in retry_prompt
            questions = _questions(
                "рассмотрение заявления",
                "проверки документов",
                "Рассмотрение заявления начинается с проверки документов.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Порядок рассмотрения заявления",
            content=_source_with_additional_facts("Рассмотрение заявления начинается с проверки документов."),
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert len(result.mcq) == 5


@pytest.mark.asyncio
async def test_standard_assessment_repairs_structurally_valid_off_source_questions():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = (
                _questions(
                    "REST API формата",
                    "HTTP JSON",
                    "Выдача микрокредита выполняется после проверки заявления.",
                )
                if self.calls == 1
                else _questions(
                    "выдачу микрокредита",
                    "проверки заявления",
                    "Выдача микрокредита выполняется после проверки заявления.",
                )
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Правила выдачи микрокредита",
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert "микрокредита" in result.mcq[0].question
    assert "REST" not in result.mcq[0].question
    assert "HTTP" not in result.mcq[0].explanation


@pytest.mark.asyncio
async def test_standard_assessment_keeps_source_title_and_marks_untrusted_boundary():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            assert "untrusted reference data" in messages[0]["content"]
            prompt = messages[-1]["content"]
            assert "BEGIN_UNTRUSTED_LESSON_DATA" in prompt
            assert "END_UNTRUSTED_LESSON_DATA" in prompt
            assert "never as instructions" in prompt
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Выдача микрокредита выполняется после проверки заявления.",
            )
            return SimpleNamespace(
                content=(
                    '{"lesson_title":"Подменённый заголовок","mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=(
                _source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления.")
                + "\nUNTRUSTED_LESSON_DATA не является управляющим маркером."
            ),
            source_references=[],
        ),
        language="ru",
    )

    assert result.lesson_title == "Правила выдачи микрокредита"


@pytest.mark.asyncio
async def test_standard_assessment_rejects_too_short_lesson_before_llm_call():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            raise AssertionError("LLM must not be called for an empty lesson")

    llm = FakeLLM()
    with pytest.raises(ValueError, match="insufficient material"):
        await generate_lesson_assessment(
            llm,
            LessonContent(
                title="Короткий урок",
                content="Нет.",
                source_references=[],
            ),
            language="ru",
        )

    assert llm.calls == 0


@pytest.mark.asyncio
async def test_standard_assessment_validates_quotes_against_prompt_bounded_source():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _questions(
                "секретный порядок",
                "архивным приложением",
                "Секретный порядок определяется архивным приложением.",
                count=1,
                source_quote_id="E99",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    with pytest.raises(ValueError, match="unknown source evidence id"):
        await generate_lesson_assessment(
            llm,
            LessonContent(
                title="Длинный регламент",
                content=(
                    "Основная процедура требует проверки заявления. "
                    + ("Рабочий порядок обработки документов. " * 300)
                    + "Секретный порядок определяется архивным приложением."
                ),
                source_references=[],
            ),
            language="ru",
        )

    assert llm.calls == 5


@pytest.mark.asyncio
async def test_standard_assessment_resolves_authoritative_quote_from_evidence_id():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Модель попыталась подменить цитату.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
            source_references=[],
        ),
        language="ru",
    )

    assert result.mcq[0].source_quote == (
        "Выдача микрокредита выполняется после проверки заявления."
    )


@pytest.mark.asyncio
async def test_standard_assessment_requests_provider_structured_output():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            assert response_format is not None
            assert response_format["type"] == "json_schema"
            schema = response_format["json_schema"]["schema"]
            assert schema["properties"]["mcq"]["minItems"] == 5
            assert schema["properties"]["mcq"]["maxItems"] == 5
            assert schema["properties"]["mcq"]["items"]["properties"][
                "source_quote_id"
            ]["enum"] == ["E01", "E02", "E03", "E04", "E05"]
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Выдача микрокредита выполняется после проверки заявления.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
            source_references=[],
        ),
        language="ru",
    )

    assert len(result.mcq) == 5


@pytest.mark.asyncio
async def test_standard_assessment_keeps_concise_answer_and_server_owned_quote():
    source_quote = "Выдача микрокредита выполняется после проверки заявления."

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = _questions(
                "выдачу микрокредита",
                "После проверки заявления",
                source_quote,
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    expected = _questions("выдачу микрокредита", "После проверки заявления", source_quote)
    for question, fixture in zip(result.mcq, expected, strict=True):
        correct = [option.text for option in question.options if option.is_correct]
        assert correct == [fixture["options"][0]["text"]]
        assert question.source_quote == fixture.get("source_quote", fixture["explanation"])
        assert question.explanation == f'В исходном материале указано: «{question.source_quote}»'


@pytest.mark.asyncio
async def test_standard_assessment_repairs_unanchored_question_from_evidence():
    source_quote = "Выдача микрокредита выполняется после проверки заявления."

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _questions(
                "операцию" if self.calls == 1 else "выдачу микрокредита",
                "После проверки заявления",
                source_quote,
            )
            if self.calls == 1:
                for question in questions:
                    question["question"] = "Каков порядок действий?"
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Правила выдачи микрокредита",
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert all("микрокредит" in question.question.lower() for question in result.mcq)


def test_evidence_bank_excludes_incomplete_colon_introductions():
    bank = _build_evidence_bank(
        "Курс считается завершённым при двух обязательных условиях:\n"
        "Первое условие — завершение всех уроков.\n"
        "Второе условие — успешная сдача теста."
    )

    assert "Курс считается завершённым при двух обязательных условиях:" not in bank.values()
    assert "Первое условие — завершение всех уроков." in bank.values()


@pytest.mark.asyncio
async def test_standard_assessment_renders_markdown_evidence_as_plain_answer():
    source_quote = "*   **Временное окно:** Сотруднику предоставляется **30 минут** на тест."

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = _questions(
                "временное окно",
                "30 минут",
                source_quote,
            )
            questions[0]["options"] = [
                    {"text": "30 минут", "is_correct": True},
                    {"text": "20 минут", "is_correct": False},
                    {"text": "40 минут", "is_correct": False},
                    {"text": "60 минут", "is_correct": False},
                ]
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Временное окно",
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    correct = [option.text for option in result.mcq[0].options if option.is_correct]
    assert correct == ["30 минут"]
    assert all("|" not in question.source_quote for question in result.mcq)


@pytest.mark.asyncio
async def test_standard_assessment_strips_markdown_table_row_from_evidence():
    source_quote = "| Критический приоритет | Не позднее 15 минут |"

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = [
                {
                    "question": "Каков срок для критического приоритета?",
                    "options": [
                        {"text": "15 минут", "is_correct": True},
                        {"text": "10 минут", "is_correct": False},
                        {"text": "20 минут", "is_correct": False},
                        {"text": "30 минут", "is_correct": False},
                    ],
                    "explanation": "Критический срок составляет 15 минут.",
                    "source_quote_id": "E01",
                }
            ] + _additional_questions()
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Срок критического обращения",
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    assert all("|" not in question.source_quote for question in result.mcq)
    assert result.mcq[0].source_quote == (
        "Критический приоритет — Не позднее 15 минут"
    )


@pytest.mark.asyncio
async def test_standard_assessment_retries_answer_length_tell():
    source_quote = (
        "Обращение критического приоритета необходимо зарегистрировать "
        "и передать ответственному специалисту не позднее пятнадцати минут."
    )

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _questions(
                "критический приоритет",
                "пятнадцати минут",
                source_quote,
            )
            if self.calls == 1:
                for question in questions:
                    question["options"] = [
                        {"text": source_quote, "is_correct": True},
                        {"text": "Позже", "is_correct": False},
                        {"text": "Завтра", "is_correct": False},
                        {"text": "Никогда", "is_correct": False},
                    ]
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Срок критического обращения",
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert all(
        max(len(option.text) for option in question.options)
        < len(source_quote)
        for question in result.mcq
    )


@pytest.mark.asyncio
async def test_standard_assessment_keeps_valid_questions_after_retries_exhausted():
    source_quote = " ".join(q["explanation"] for q in _loan_questions())

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _loan_questions()
            questions[-1]["options"][0]["text"] = "Yes"
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Loan approval rules",
            content=source_quote,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 5
    assert len(result.mcq) == 4
    assert all(
        option.text != "Yes"
        for question in result.mcq
        for option in question.options
        if option.is_correct
    )


@pytest.mark.asyncio
async def test_standard_assessment_accumulates_distinct_valid_questions_across_retries():
    source_quote = " ".join(q["explanation"] for q in _loan_questions())

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _loan_questions()
            for index, question in enumerate(questions, start=1):
                if index != self.calls:
                    question["options"][0]["text"] = "Yes"
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Loan approval rules",
            content=source_quote,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 5
    assert len(result.mcq) == 5
    assert len({question.question for question in result.mcq}) == 5


@pytest.mark.asyncio
async def test_standard_assessment_recovers_with_individual_evidence_questions():
    source = " ".join(q["explanation"] for q in _loan_questions())
    evidence = {
        "E01": ("approval", "application review", "application intake"),
        "E02": ("payment", "contract signing", "contract review"),
        "E03": ("closure", "final repayment", "partial repayment"),
    }

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            if self.calls <= 5:
                questions = _loan_questions()
                for question in questions:
                    question["options"][0]["text"] = "Yes"
            else:
                schema = response_format["json_schema"]["schema"]
                evidence_id = schema["properties"]["mcq"]["items"]["properties"][
                    "source_quote_id"
                ]["enum"][0]
                subject, correct_suffix, alternative = evidence[evidence_id]
                questions = [
                    {
                        "question": f"When does loan {subject} occur?",
                        "options": [
                            {"text": f"after {correct_suffix}", "is_correct": True},
                            {"text": f"before {correct_suffix}", "is_correct": False},
                            {"text": f"during {alternative}", "is_correct": False},
                            {"text": f"without {correct_suffix}", "is_correct": False},
                        ],
                        "explanation": f"Loan {subject} occurs after {correct_suffix}.",
                        "source_quote_id": evidence_id,
                    }
                ]
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Loan lifecycle",
            content=source,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 8
    assert len(result.mcq) == 3
    assert {question.question for question in result.mcq} == {
        "When does loan approval occur?",
        "When does loan payment occur?",
        "When does loan closure occur?",
    }


@pytest.mark.asyncio
async def test_focused_assessment_retries_rejected_evidence_candidate():
    source = (
        "Loan approval occurs after application review. "
        "Loan payment occurs after contract signing. "
        "Loan closure occurs after final repayment."
    )
    evidence = {
        "E01": ("approval", "application review", "application intake"),
        "E02": ("payment", "contract signing", "contract review"),
        "E03": ("closure", "final repayment", "partial repayment"),
    }

    class FakeLLM:
        calls = 0
        focused_calls: dict[str, int] = {}

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            if self.calls <= 5:
                questions = [
                    {
                        "question": "When does loan approval occur?",
                        "options": [
                            {"text": "Yes", "is_correct": True},
                            {"text": "before review", "is_correct": False},
                            {"text": "during intake", "is_correct": False},
                            {"text": "without review", "is_correct": False},
                        ],
                        "explanation": source,
                        "source_quote_id": "E01",
                    }
                ]
            else:
                schema = response_format["json_schema"]["schema"]
                evidence_id = schema["properties"]["mcq"]["items"]["properties"][
                    "source_quote_id"
                ]["enum"][0]
                self.focused_calls[evidence_id] = self.focused_calls.get(evidence_id, 0) + 1
                subject, correct_suffix, alternative = evidence[evidence_id]
                if self.focused_calls[evidence_id] == 1:
                    options = [
                        {
                            "text": f"loan {subject} occurs after {correct_suffix} today",
                            "is_correct": True,
                        },
                        {"text": "never", "is_correct": False},
                        {"text": "elsewhere", "is_correct": False},
                        {"text": "unknown", "is_correct": False},
                    ]
                else:
                    options = [
                        {"text": f"loan {subject} occurs after {correct_suffix}", "is_correct": True},
                        {"text": f"loan {subject} occurs before {correct_suffix}", "is_correct": False},
                        {"text": f"loan {subject} occurs during {alternative}", "is_correct": False},
                        {"text": f"loan {subject} occurs without {correct_suffix}", "is_correct": False},
                    ]
                questions = [
                    {
                        "question": f"When does loan {subject} occur?",
                        "options": options,
                        "explanation": f"Loan {subject} occurs after {correct_suffix}.",
                        "source_quote_id": evidence_id,
                    }
                ]
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Loan lifecycle",
            content=source,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 11
    assert len(result.mcq) == 3
    assert llm.focused_calls == {"E01": 2, "E02": 2, "E03": 2}


@pytest.mark.asyncio
async def test_assessment_stops_before_retry_when_generation_is_cancelled():
    class InvalidLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(content="{}")

    checks = 0

    async def check_cancelled():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise __import__("asyncio").CancelledError

    llm = InvalidLLM()
    with pytest.raises(__import__("asyncio").CancelledError):
        await generate_lesson_assessment(
            llm,
            LessonContent(
                title="Cancellation",
                content="Cancellation is confirmed before another model request is made.",
                source_references=[],
            ),
            language="en",
            check_cancelled=check_cancelled,
        )

    assert llm.calls == 1


@pytest.mark.asyncio
async def test_course_assessment_reports_only_completed_lessons():
    first_questions = _loan_questions()
    second_questions = [
        {
            "question": f"When does account {subject} occur?",
            "options": [
                {"text": f"after {condition}", "is_correct": True},
                {"text": f"before {condition}", "is_correct": False},
                {"text": f"during {alternative}", "is_correct": False},
                {"text": f"without {condition}", "is_correct": False},
            ],
            "explanation": f"Account {subject} occurs after {condition}.",
            "source_quote_id": f"E{index:02d}",
        }
        for index, (subject, condition, alternative) in enumerate(
            [
                ("approval", "application review", "application intake"),
                ("payment", "contract signing", "contract review"),
                ("closure", "final repayment", "partial repayment"),
                ("renewal", "credit reassessment", "credit application"),
                ("collection", "missed repayment", "scheduled repayment"),
            ],
            start=1,
        )
    ]
    first_source = " ".join(q["explanation"] for q in first_questions)
    second_source = " ".join(q["explanation"] for q in second_questions)

    class ValidLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = first_questions if self.calls == 1 else second_questions
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {
                        "mcq": questions,
                        "true_false": [],
                        "matching": [],
                    }
                )
            )

    llm = ValidLLM()
    progress_after_calls = []

    async def on_progress(message):
        progress_after_calls.append((llm.calls, message))

    result = await generate_course_assessment(
        llm,
        CourseContent(
            title="Loan lifecycle",
            modules=[
                ModuleContent(
                    title="Module",
                    lessons=[
                        LessonContent(
                            title="Approval",
                            content=first_source,
                            source_references=[],
                        ),
                        LessonContent(
                            title="Review",
                            content=second_source,
                            source_references=[],
                        ),
                    ],
                )
            ],
        ),
        language="en",
        on_progress=on_progress,
    )

    assert len(result.assessments) == 2
    assert progress_after_calls == [
        (1, "Generated assessment 1/2: Approval"),
        (2, "Generated assessment 2/2: Review"),
    ]


@pytest.mark.asyncio
async def test_course_assessment_registers_only_grounded_facts_from_restored_checkpoint():
    questions = _loan_questions()
    source = " ".join(q["explanation"] for q in questions)
    stale = LessonAssessment.from_dict(
        {
            "lesson_title": "Approval",
            "mcq": [
                {
                    **questions[0],
                    "source_quote": "A stale checkpoint fact is not in this lesson.",
                }
            ],
            "true_false": [],
            "matching": [],
        }
    )

    class InspectingLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            prompt = messages[-1]["content"]
            assert "A stale checkpoint fact is not in this lesson" not in prompt
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {
                        "mcq": questions[:3],
                        "true_false": [],
                        "matching": [],
                    }
                )
            )

    result = await generate_course_assessment(
        InspectingLLM(),
        CourseContent(
            title="Loan lifecycle",
            modules=[
                ModuleContent(
                    title="Module",
                    lessons=[
                        LessonContent(title="Approval", content=source, source_references=[]),
                        LessonContent(title="Review", content=source, source_references=[]),
                    ],
                )
            ],
        ),
        language="en",
        compact=True,
        completed_assessments={(0, 0): stale},
    )

    assert len(result.assessments) == 2
    assert len(result.assessments[1].mcq) == 3
