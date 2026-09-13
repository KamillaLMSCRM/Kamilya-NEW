from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import (
    _answers_are_near_equivalent,
    _answers_share_distinctive_phrase,
    _assessment_contract_reason_codes,
    _assessment_question_count,
    _build_evidence_bank,
    _generate_tabular_assessment,
    _normalize_evidence_text,
    _structured_evidence_cells,
    _unsupported_named_entities,
    _validate_generated_question_set,
    _validate_question_evidence,
    capture_assessment_paths,
    generate_course_assessment,
    generate_lesson_assessment,
)
from app.modules.ai.assessment_schema import LessonAssessment
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


def test_structured_lesson_question_count_adapts_to_available_rows() -> None:
    source = "| Field | Alpha | Beta |\n| --- | --- | --- |\n| Style | modern | classic |"

    assert (
        _assessment_question_count(
            compact=False,
            evidence_bank={f"E{index:02d}": f"Fact {index}" for index in range(1, 10)},
            bounded_source=source,
        )
        == 3
    )
    assert (
        _assessment_question_count(
            compact=False,
            evidence_bank={f"E{index:02d}": f"Fact {index}" for index in range(1, 6)},
            bounded_source="Five prose facts.",
        )
        == 5
    )


def test_equivalent_structured_answers_ignore_descriptive_subject_prefix() -> None:
    assert _answers_are_near_equivalent(
        "Модульная коллекция в матовых моно-оттенках",
        "В матовых моно-оттенках",
    )


def test_semantic_overlap_requires_a_distinctive_shared_phrase() -> None:
    assert _answers_share_distinctive_phrase(
        "Одна платформа на всю квартиру",
        "Конструктор на всю квартиру",
    )
    assert _answers_share_distinctive_phrase(
        "Одна платформа на всю квартиру плюс торцевые модули",
        "Феникс — это конструктор на всю квартиру",
    )
    assert not _answers_share_distinctive_phrase(
        "Феникс в том же цвете",
        "Чикаго Стрит в том же цвете",
    )
    assert not _answers_share_distinctive_phrase(
        "ЛДСП Kronospan (Австрия)",
        "МДФ Kronospan (Австрия)",
    )
    assert _answers_are_near_equivalent(
        "Интерьерная платформа Imperial: модульный конструктор из нескольких дизайн-серий",
        "Модульный конструктор из нескольких дизайн-серий",
    )


def test_structured_evidence_cells_accepts_sentence_split_markdown_row() -> None:
    assert _structured_evidence_cells(
        "| Что это за коллекция | Интерьерная платформа Imperial: модульный конструктор."
    ) == [
        "Что это за коллекция",
        "Интерьерная платформа Imperial: модульный конструктор.",
    ]


def test_structured_question_rejects_ambiguous_generic_subject() -> None:
    source = (
        "| Коллекция | Описание |\n"
        "| --- | --- |\n"
        "| Феникс | Интерьерная платформа для всей квартиры |\n"
        "| Чикаго Нео | Модульная коллекция в матовых моно-оттенках |"
    )
    evidence = "| Чикаго Нео | Модульная коллекция в матовых моно-оттенках |"
    payload = {
        "mcq": [
            {
                "question": "В каких оттенках представлена модульная коллекция?",
                "options": [
                    {"text": "в матовых моно-оттенках", "is_correct": True},
                    {"text": "в глянцевых древесных оттенках", "is_correct": False},
                    {"text": "в ярких контрастных оттенках", "is_correct": False},
                    {"text": "в пастельных двухцветных оттенках", "is_correct": False},
                ],
                "explanation": evidence,
                "source_quote_id": "E01",
            }
        ],
        "true_false": [],
        "matching": [],
    }

    issues = _validate_question_evidence(
        payload,
        evidence_bank={"E01": evidence},
        bounded_source=source,
        language="ru",
    )

    assert "MCQ #1: structured question omits its specific subject" in issues


def test_structured_question_rejects_vague_elements_without_antecedent() -> None:
    source = "| Чикаго Стрит | Совместимы с антресолями и угловым шкафом коллекции Чикаго |"
    payload = {
        "mcq": [
            {
                "question": "С чем совместимы элементы, позволяющие закрыть комнату на 100%?",
                "options": [
                    {"text": "с антресолями и угловым шкафом", "is_correct": True},
                    {"text": "с витринами и прямым шкафом", "is_correct": False},
                    {"text": "с консолями и навесной полкой", "is_correct": False},
                    {"text": "с кроватью и прикроватной тумбой", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ],
        "true_false": [],
        "matching": [],
    }

    issues = _validate_question_evidence(
        payload,
        evidence_bank={"E01": source},
        bounded_source=source,
        language="ru",
    )

    assert "MCQ #1: structured question uses a vague subject without an antecedent" in issues


def test_structured_question_rejects_source_reference_without_named_subject() -> None:
    source = "| Чикаго Нео | Взрослый размер и матовые торцевые ручки |"
    payload = {
        "mcq": [
            {
                "question": "Какой размер и какие ручки указаны в описании?",
                "options": [
                    {"text": "Взрослый размер и матовые торцевые ручки", "is_correct": True},
                    {"text": "Компактный размер и скрытые ручки", "is_correct": False},
                    {"text": "Детский размер и накладные ручки", "is_correct": False},
                    {"text": "Увеличенный размер и глянцевые ручки", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ],
        "true_false": [],
        "matching": [],
    }

    issues = _validate_question_evidence(
        payload,
        evidence_bank={"E01": source},
        bounded_source=source,
        language="ru",
    )

    assert "MCQ #1: structured question references source without a specific subject" in issues


def test_question_leak_detection_ignores_interrogative_who_prefix() -> None:
    source = "| Кому рекомендовать | Кто делает несколько комнат в одном стиле |"
    payload = {
        "mcq": [
            {
                "question": "Кому рекомендовать коллекцию, если человек делает несколько комнат в одном стиле?",
                "options": [
                    {"text": "Кто делает несколько комнат в одном стиле", "is_correct": True},
                    {"text": "Кто оформляет одну комнату без хранения", "is_correct": False},
                    {"text": "Кто выбирает разные стили для комнат", "is_correct": False},
                    {"text": "Кто подбирает мебель только для офиса", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ],
        "true_false": [],
        "matching": [],
    }

    issues = _validate_question_evidence(
        payload,
        evidence_bank={"E01": source},
        bounded_source=source,
        language="ru",
    )

    assert "MCQ #1: question contains its correct answer" in issues


def test_three_word_options_that_change_only_one_position_are_low_information() -> None:
    payload = {
        "mcq": [
            {
                "question": "Какие направляющие используются в консолях Феникс?",
                "options": [
                    {"text": "роликовые полного выдвижения", "is_correct": False},
                    {"text": "телескопические полного выдвижения", "is_correct": True},
                    {"text": "шариковые полного выдвижения", "is_correct": False},
                    {"text": "скрытые полного выдвижения", "is_correct": False},
                ],
                "explanation": "Телескопические полного выдвижения",
            }
        ]
    }

    issues = _validate_generated_question_set(payload, "ru")

    assert any("low_information_distractors" in issue for issue in issues)


def test_question_rejects_when_it_reveals_most_of_a_long_correct_answer() -> None:
    source = "| Профиль покупателя Феникс | хочет матовый минимализм с акцентом ручки |"
    payload = {
        "mcq": [
            {
                "question": "Какой стиль хочет покупатель с акцентом ручки и нормальными габаритами?",
                "options": [
                    {"text": "хочет глянцевый минимализм с акцентом ручки", "is_correct": False},
                    {"text": "хочет матовый максимализм с акцентом ручки", "is_correct": False},
                    {"text": "хочет матовый минимализм с акцентом ручки", "is_correct": True},
                    {"text": "хочет матовый минимализм без акцента ручки", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ],
        "true_false": [],
        "matching": [],
    }

    issues = _validate_question_evidence(
        payload,
        evidence_bank={"E01": source},
        bounded_source=source,
        language="ru",
    )

    assert "MCQ #1: question contains its correct answer" in issues


def test_three_word_role_actions_are_not_treated_as_mechanical_distractors() -> None:
    payload = {
        "mcq": [
            {
                "question": "Какие обязанности выполняет кассир?",
                "options": [
                    {"text": "Кассир принимает наличные", "is_correct": True},
                    {"text": "Кассир проверяет наличные", "is_correct": False},
                    {"text": "Кассир хранит наличные", "is_correct": False},
                    {"text": "Кассир пересчитывает наличные", "is_correct": False},
                ],
                "explanation": "Кассир принимает наличные.",
            }
        ]
    }

    issues = _validate_generated_question_set(payload, "ru")

    assert not any("low_information_distractors" in issue for issue in issues)


def _additional_questions() -> list[dict]:
    facts = [
        (
            "Когда передают график микрокредита?",
            "График микрокредита передают после подписания договора.",
            [
                "После подписания договора",
                "До подписания договора",
                "При обсуждении договора",
                "Без подписания договора",
            ],
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
        "Как в исходном материале описаны цвета коллекции Чикаго Стрит?",
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
                    "explanation": ("В исходном материале указано: что именно разберём в этом уроке."),
                }
            ]
        },
        "ru",
    )

    assert issues
    assert any("malformed_question" in issue for issue in issues)


def test_generation_contract_blocks_contextless_comparison_question() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Чем отличается от двух других?",
                    "options": [
                        {"text": "единая платформа для квартиры", "is_correct": True},
                        {"text": "открытые секции для прихожей", "is_correct": False},
                        {"text": "компактное решение для студии", "is_correct": False},
                        {"text": "контрастные фасады для спальни", "is_correct": False},
                    ],
                    "explanation": "Коллекция использует единую платформу для квартиры.",
                }
            ]
        },
        "ru",
    )

    assert any("malformed_question" in issue for issue in issues)


def test_generation_contract_blocks_invented_named_entity_in_distractor() -> None:
    source = "Феникс — единая платформа для квартиры. Чикаго — открытые секции для прихожей."
    data = {
        "mcq": [
            {
                "question": "Какое преимущество указано для коллекции Феникс?",
                "options": [
                    {"text": "единая платформа для квартиры", "is_correct": True},
                    {"text": "линейка Бостона для спальни", "is_correct": False},
                    {"text": "открытые секции для прихожей", "is_correct": False},
                    {"text": "контрастные фасады для спальни", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("unsupported named entity" in issue for issue in issues)


def test_generation_contract_blocks_incorrect_option_supported_by_selected_evidence() -> None:
    source = "| Для каких комнат | Спальня (шкафы и хранение), прихожая, " "гостиная, гардеробная. |"
    data = {
        "mcq": [
            {
                "question": "Для каких комнат предназначены шкафы и хранение?",
                "options": [
                    {"text": "Спальня (шкафы и хранение)", "is_correct": True},
                    {"text": "Прихожая", "is_correct": False},
                    {"text": "Гостиная", "is_correct": False},
                    {"text": "Гардеробная", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("incorrect option is also supported by selected source evidence" in issue for issue in issues)


def test_generation_contract_blocks_question_that_contains_its_correct_answer() -> None:
    source = "Кому нужна гостиная + шкафы, а не кровать в том же артикуле."
    data = {
        "mcq": [
            {
                "question": (
                    "Что важно подчеркнуть покупателю, которому нужна гостиная "
                    "и шкафы, но не кровать в том же артикуле?"
                ),
                "options": [
                    {"text": "Кому нужна гостиная + шкафы", "is_correct": True},
                    {"text": "Кому нужна спальня с кроватью", "is_correct": False},
                    {"text": "Кому нужна только прихожая", "is_correct": False},
                    {"text": "Кому нужна детская с витринами", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("question contains its correct answer" in issue for issue in issues)


def test_generation_contract_blocks_reused_correct_answer_from_another_lesson() -> None:
    source = "Коллекция выполнена в матовых моно-оттенках."
    previous = frozenset(
        {
            (
                _normalize_evidence_text(source),
                _normalize_evidence_text("в матовых моно-оттенках"),
            )
        }
    )
    data = {
        "mcq": [
            {
                "question": "В каких оттенках выполнена коллекция?",
                "options": [
                    {"text": "в матовых моно-оттенках", "is_correct": True},
                    {"text": "в глянцевых моно-оттенках", "is_correct": False},
                    {"text": "в матовых контрастных оттенках", "is_correct": False},
                    {"text": "в глянцевых контрастных оттенках", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(
        data,
        {"E01": source},
        source,
        "ru",
        previous,
    )

    assert any(
        "repeats source evidence and correct answer already assessed in another lesson" in issue for issue in issues
    )


def test_generation_contract_allows_same_answer_for_a_distinct_source_fact() -> None:
    source = "| Сравнение | единый стиль | открытые секции | малые комнаты |"
    previous = frozenset(
        {
            (
                _normalize_evidence_text("| Аргументация | единый стиль | сочетание фактур | экономия места |"),
                _normalize_evidence_text("единый стиль"),
            )
        }
    )
    data = {
        "mcq": [
            {
                "question": "Какая характеристика сравнения относится к Фениксу?",
                "options": [
                    {"text": "единый стиль", "is_correct": True},
                    {"text": "открытые секции", "is_correct": False},
                    {"text": "малые комнаты", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(
        data,
        {"E01": source},
        source,
        "ru",
        previous,
    )

    assert not any("already assessed in another lesson" in issue for issue in issues)


def test_generation_contract_blocks_two_questions_from_one_structured_source_fact() -> None:
    source = (
        "| Кому рекомендовать | Кто делает несколько комнат в одном стиле, " "любит конструктор и скрытое открывание. |"
    )
    data = {
        "mcq": [
            {
                "question": "Кому стоит рекомендовать коллекцию?",
                "options": [
                    {"text": "Любит конструктор и скрытое открывание", "is_correct": True},
                    {"text": "Любит готовый гарнитур", "is_correct": False},
                    {"text": "Любит классический стиль", "is_correct": False},
                    {"text": "Любит мягкую мебель", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            },
            {
                "question": "Какой покупатель подходит для этой коллекции?",
                "options": [
                    {"text": "Кто делает несколько комнат в одном стиле", "is_correct": True},
                    {"text": "Кто оформляет одну комнату", "is_correct": False},
                    {"text": "Кто выбирает разные стили", "is_correct": False},
                    {"text": "Кто не использует шкафы", "is_correct": False},
                ],
                "explanation": source,
                "source_quote_id": "E01",
            },
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("reuses one structured source fact" in issue for issue in issues)


def test_generation_contract_blocks_equivalent_answers_from_one_structured_cell() -> None:
    source = "| Особенности кроватей | подъёмное основание | " "с основанием на гибких ламелях | мягкое изголовье |"
    data = {
        "mcq": [
            {
                "question": "На каком основании выполнена кровать Чикаго Нео?",
                "options": [
                    {"text": "с основанием на гибких ламелях", "is_correct": True},
                    {"text": "на сплошном деревянном щите", "is_correct": False},
                    {"text": "на металлической сетке", "is_correct": False},
                ],
                "source_quote_id": "E01",
            },
            {
                "question": "Чем отличается основание кровати Чикаго Нео?",
                "options": [
                    {"text": "основанием на гибких ламелях", "is_correct": True},
                    {"text": "основанием на жёсткой панели", "is_correct": False},
                    {"text": "основанием без отдельных ламелей", "is_correct": False},
                ],
                "source_quote_id": "E01",
            },
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("reuses one structured source cell" in issue for issue in issues)


def test_generation_contract_blocks_distractor_supported_by_correct_source_cell() -> None:
    source = (
        "| Кому рекомендовать | Кто делает несколько комнат в одном стиле, "
        "любит конструктор и скрытое открывание | Для небольшой комнаты |"
    )
    data = {
        "mcq": [
            {
                "question": "Кому рекомендовать модульную коллекцию?",
                "options": [
                    {
                        "text": "Кто делает несколько комнат в одном стиле",
                        "is_correct": True,
                    },
                    {
                        "text": "Кто любит конструктор и скрытое открывание",
                        "is_correct": False,
                    },
                    {"text": "Кто выбирает готовый комплект", "is_correct": False},
                ],
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("incorrect option is also supported by the correct source cell" in issue for issue in issues)


def test_generation_contract_blocks_opaque_compact_source_shorthand_in_options() -> None:
    source = "| Особенности комодов | два ящика | три ящика | " "1д4ящ с закрытым отделением |"
    data = {
        "mcq": [
            {
                "question": "Какая особенность указана для комода?",
                "options": [
                    {"text": "два ящика", "is_correct": True},
                    {"text": "три ящика", "is_correct": False},
                    {
                        "text": "1д4ящ с закрытым отделением",
                        "is_correct": False,
                    },
                ],
                "source_quote_id": "E01",
            }
        ]
    }

    issues = _validate_question_evidence(data, {"E01": source}, source, "ru")

    assert any("opaque compact source shorthand" in issue for issue in issues)


@pytest.mark.parametrize(
    "option, source, expected",
    [
        ("Бостон — линейка для спальни", "Феникс — линейка для прихожей", ("Бостон",)),
        ("линейка Өркен для спальни", "Феникс — линейка для прихожей", ("Өркен",)),
        ("Коллекция подходит для прихожей", "Коллекция Феникс подходит для прихожей", ()),
    ],
)
def test_named_entity_guard_handles_leading_labels_and_kazakh_letters(
    option: str,
    source: str,
    expected: tuple[str, ...],
) -> None:
    assert _unsupported_named_entities(option, source) == expected


def test_generation_contract_blocks_choices_that_change_one_middle_token() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Как описана комплектация коллекции?",
                    "options": [
                        {"text": "в комплект входят зеркала и вешалки", "is_correct": True},
                        {"text": "в комплект входят полки и вешалки", "is_correct": False},
                        {"text": "в комплект входят столы и вешалки", "is_correct": False},
                        {"text": "в комплект входят шкафы и вешалки", "is_correct": False},
                    ],
                    "explanation": "В комплект входят зеркала и вешалки.",
                }
            ]
        },
        "ru",
    )

    assert any("low_information_distractors" in issue for issue in issues)


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


def test_generation_contract_allows_shared_intro_with_substantive_options() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "С какими коллекциями совместима Чикаго Стрит?",
                    "options": [
                        {"text": "Совместима с коллекциями Чикаго и Чикаго Нео", "is_correct": True},
                        {"text": "Совместима с коллекциями Феникс и Вайт", "is_correct": False},
                        {"text": "Совместима с коллекциями Imperial и Феникс", "is_correct": False},
                        {"text": "Совместима с коллекциями Феникс Один и Два", "is_correct": False},
                    ],
                    "explanation": "Чикаго Стрит совместима с Чикаго и Чикаго Нео.",
                }
            ]
        },
        "ru",
    )

    assert not any("low_information_distractors" in issue for issue in issues)


def test_generation_contract_blocks_choices_with_repeated_long_tail() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Какое главное преимущество коллекции Феникс?",
                    "options": [
                        {"text": "Одна платформа на всю квартиру", "is_correct": True},
                        {"text": "Одна платформа на всю спальню", "is_correct": False},
                        {"text": "Одна платформа на всю прихожую", "is_correct": False},
                        {"text": "Одна платформа на всю витрину", "is_correct": False},
                    ],
                    "explanation": "Главное преимущество — одна платформа на всю квартиру.",
                }
            ]
        },
        "ru",
    )

    assert any("low_information_distractors" in issue for issue in issues)


def test_generation_contract_allows_parallel_options_without_long_repeated_frame() -> None:
    issues = _validate_generated_question_set(
        {
            "mcq": [
                {
                    "question": "Когда выполняют проверку товара?",
                    "options": [
                        {"text": "Проверку товара выполняют утром до открытия", "is_correct": True},
                        {"text": "Проверку товара выполняют вечером после смены", "is_correct": False},
                        {"text": "Проверку товара выполняют ночью при тревоге", "is_correct": False},
                        {"text": "Проверку товара выполняют днём по графику", "is_correct": False},
                    ],
                    "explanation": "Проверку товара выполняют утром до открытия.",
                }
            ]
        },
        "ru",
    )

    assert not any("low_information_distractors" in issue for issue in issues)


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
        next(option.text for option in question.options if option.is_correct) in scenario_answers
        for question in result.mcq
    )
    assert all(len(question.options) == 4 for question in result.mcq)
    assert all(
        (
            _normalize_evidence_text(question.source_quote),
            _normalize_evidence_text(next(option.text for option in question.options if option.is_correct)),
        )
        not in excluded
        for question in result.mcq
    )


def test_three_subject_table_uses_three_grounded_options_without_model_fallback() -> None:
    source = "\n".join(
        [
            "# [Worksheet] Коллекции",
            "",
            "| Коллекция | Стиль | Материал | Сценарий консультации |",
            "| --- | --- | --- | --- |",
            "| Феникс | современный минимализм | ЛДСП | уточнить комнаты |",
            "| Чикаго Нео | строгий минимализм | МДФ | согласовать стиль |",
            "| Чикаго Стрит | городской минимализм | металл | показать модули |",
        ]
    )
    evidence_bank = _build_evidence_bank(source)

    result = _generate_tabular_assessment(
        evidence_bank=evidence_bank,
        bounded_source=source,
        lesson_title="Стили коллекций",
        lesson_objectives=["Различать стиль каждой коллекции"],
        language="ru",
        question_count=3,
    )

    assert result is not None
    assert len(result.mcq) == 3
    assert all(len(question.options) == 3 for question in result.mcq)
    source_values = {
        "современный минимализм",
        "строгий минимализм",
        "городской минимализм",
    }
    assert {option.text for question in result.mcq for option in question.options} == source_values


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
    correct_answers = {next(option.text for option in question.options if option.is_correct) for question in result.mcq}
    assert {
        "показать механизм открывания",
        "уточнить объём хранения",
        "собрать требования к высоте",
    } <= correct_answers
    assert len(result.mcq) == 5


def test_tabular_assessment_uses_all_three_distinct_peer_values() -> None:
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

    assert result is not None
    assert len(result.mcq) == 3
    assert all(len(question.options) == 3 for question in result.mcq)


def test_tabular_assessment_caps_options_at_four_with_more_peer_values() -> None:
    source = "\n".join(
        [
            "| Коллекция | Стиль |",
            "| --- | --- |",
            "| Альфа | современный |",
            "| Бета | скандинавский |",
            "| Гамма | лофт |",
            "| Дельта | минимализм |",
            "| Эпсилон | классический |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Стили коллекций",
        lesson_objectives=["Различать стиль каждой коллекции"],
        language="ru",
        question_count=5,
    )

    assert result is not None
    assert len(result.mcq) == 5
    assert all(len(question.options) == 4 for question in result.mcq)
    assert all(option.text in source for question in result.mcq for option in question.options)


def test_tabular_assessment_adapts_to_available_structured_facts() -> None:
    source = "\n".join(
        [
            "Альфа — современный — ЛДСП — белый",
            "Бета — скандинавский — МДФ — серый",
            "Гамма — лофт — металл — чёрный",
        ]
    )
    lesson_body = "\n".join(
        [
            "### Альфа",
            "| Характеристика | Значение |",
            "| --- | --- |",
            "| Стиль | современный |",
            "| Материал | ЛДСП |",
            "| Цвет | белый |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Характеристики коллекции Альфа",
        lesson_objectives=["Консультировать по коллекции Альфа"],
        lesson_body=lesson_body,
        language="ru",
        question_count=5,
    )

    assert result is not None
    assert len(result.mcq) == 3
    assert all(len(question.options) == 3 for question in result.mcq)


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
    assert (
        sum(
            next(option.text for option in question.options if option.is_correct) == "современный"
            for question in result.mcq
        )
        == 2
    )


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
    assert all(any(subject in question.question for subject in {"Альфа", "Бета", "Гамма"}) for question in result.mcq)
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
    assert all(any(subject in question.question for subject in {"Альфа", "Бета", "Гамма"}) for question in result.mcq)
    assert all(option.text in source for question in result.mcq for option in question.options)


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
    assert all("«Альфа»" in question.question or "«Бета»" in question.question for question in result.mcq)
    assert all(
        any(option.text in evidence for evidence in _build_evidence_bank(source).values())
        for question in result.mcq
        for option in question.options
    )


def test_vertical_three_collection_cards_keep_each_question_within_one_attribute() -> None:
    source = "\n".join(
        [
            "| Поле | Феникс | Чикаго Нео | Чикаго Стрит |",
            "| --- | --- | --- | --- |",
            "| Фасады | гладкие фасады | комбинированные фасады | рамочные фасады |",
            "| Механизмы | скрытое открывание | роликовые направляющие | накладные петли |",
            "| Комплектация | модульные шкафы | готовые прихожие | настенные зеркала |",
        ]
    )
    lesson_body = "\n\n".join(
        [
            "## Феникс\n| Характеристика | Значение |\n| --- | --- |\n"
            "| Фасады | гладкие фасады |\n| Механизмы | скрытое открывание |\n| Комплектация | модульные шкафы |",
            "## Чикаго Нео\n| Характеристика | Значение |\n| --- | --- |\n"
            "| Фасады | комбинированные фасады |\n| Механизмы | роликовые направляющие |\n| Комплектация | готовые прихожие |",
            "## Чикаго Стрит\n| Характеристика | Значение |\n| --- | --- |\n"
            "| Фасады | рамочные фасады |\n| Механизмы | накладные петли |\n| Комплектация | настенные зеркала |",
        ]
    )

    result = _generate_tabular_assessment(
        evidence_bank=_build_evidence_bank(source),
        bounded_source=source,
        lesson_title="Коллекции: Фасады, Механизмы и Комплектация",
        lesson_objectives=["Сопоставлять характеристики трёх коллекций"],
        lesson_body=lesson_body,
        language="ru",
        question_count=5,
    )

    assert result is not None
    attribute_value_sets = (
        {"гладкие фасады", "комбинированные фасады", "рамочные фасады"},
        {"скрытое открывание", "роликовые направляющие", "накладные петли"},
        {"модульные шкафы", "готовые прихожие", "настенные зеркала"},
    )
    assert all(
        any({option.text for option in question.options} == values for values in attribute_value_sets)
        for question in result.mcq
    )
    assert all(
        any(name in question.question for name in {"Феникс", "Чикаго Нео", "Чикаго Стрит"}) for question in result.mcq
    )


def test_vertical_collection_cards_map_to_plain_converter_rows() -> None:
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
    lesson_body = "\n\n".join(
        [
            "## Альфа",
            "| Характеристика | Значение |",
            "| --- | --- |",
            "| Стиль | современный |",
            "| Преимущество для клиента | модульная компоновка |",
            "| Материал | ЛДСП |",
            "| Сценарий консультации | уточнить размеры помещения |",
            "",
            "## Бета",
            "| Характеристика | Значение |",
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
        lesson_title="Коллекции: Альфа и Бета",
        lesson_objectives=["Сопоставлять характеристики коллекций"],
        lesson_body=lesson_body,
        language="ru",
        question_count=2,
    )

    assert result is not None
    assert len(result.mcq) == 2
    assert all("«Альфа»" in question.question or "«Бета»" in question.question for question in result.mcq)


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
    assert all("«Альфа»" in question.question or "«Бета»" in question.question for question in result.mcq)


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
async def test_model_assessment_keeps_valid_questions_without_padding_after_duplicate() -> None:
    source = "| Особенности кроватей | Чикаго Нео | " "с основанием на гибких ламелях |"

    class LLMWithOneDuplicate:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(
                content="""{
                    "mcq": [
                        {
                            "question": "На каком основании выполнена кровать Чикаго Нео?",
                            "options": [
                                {"text": "с основанием на гибких ламелях", "is_correct": true},
                                {"text": "на сплошном деревянном щите", "is_correct": false},
                                {"text": "на металлической сетке", "is_correct": false}
                            ],
                            "explanation": "с основанием на гибких ламелях",
                            "source_quote_id": "E01"
                        },
                        {
                            "question": "Чем отличается основание кровати Чикаго Нео?",
                            "options": [
                                {"text": "основанием на гибких ламелях", "is_correct": true},
                                {"text": "основанием на жёсткой панели", "is_correct": false},
                                {"text": "основанием без отдельных ламелей", "is_correct": false}
                            ],
                            "explanation": "основанием на гибких ламелях",
                            "source_quote_id": "E01"
                        },
                        {
                            "question": "Для какой коллекции указаны гибкие ламели?",
                            "options": [
                                {"text": "Чикаго Нео", "is_correct": true},
                                {"text": "Первая коллекция", "is_correct": false},
                                {"text": "Базовая коллекция", "is_correct": false}
                            ],
                            "explanation": "Чикаго Нео",
                            "source_quote_id": "E01"
                        }
                    ],
                    "true_false": [],
                    "matching": []
                }"""
            )

    llm = LLMWithOneDuplicate()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Кровати коллекции Чикаго Нео",
            objectives=["Объяснять особенности основания кровати"],
            content="Generated prose is not evidence.",
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
        compact=True,
    )

    assert llm.calls == 1
    assert len(result.mcq) == 2
    assert (
        sum(
            "гибких ламелях" in next(option.text for option in question.options if option.is_correct)
            for question in result.mcq
        )
        == 1
    )


@pytest.mark.asyncio
async def test_model_assessment_drops_cross_row_paraphrase_without_padding() -> None:
    source = "\n".join(
        (
            "| Главное преимущество | Одна платформа на всю квартиру |",
            "| Что сказать покупателю | Феникс — это конструктор на всю квартиру |",
            "| Альтернатива спальни | Один гарнитур на одну спальню |",
            "| Альтернатива гостиной | Одна витрина на одну гостиную |",
            "| Альтернатива прихожей | Одна консоль на одну прихожую |",
        )
    )

    class LLMWithCrossRowParaphrase:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(
                content="""{
                    "mcq": [
                        {
                            "question": "Какое главное преимущество указано для Феникса?",
                            "options": [
                                {"text": "Одна платформа на всю квартиру", "is_correct": true},
                                {"text": "Один гарнитур на одну спальню", "is_correct": false},
                                {"text": "Одна витрина на одну гостиную", "is_correct": false},
                                {"text": "Одна консоль на одну прихожую", "is_correct": false}
                            ],
                            "explanation": "Одна платформа на всю квартиру",
                            "source_quote_id": "E01"
                        },
                        {
                            "question": "Как описать Феникс покупателю?",
                            "options": [
                                {"text": "Конструктор на всю квартиру", "is_correct": true},
                                {"text": "Гарнитур на одну спальню", "is_correct": false},
                                {"text": "Комплект на одну прихожую", "is_correct": false},
                                {"text": "Набор на одну гостиную", "is_correct": false}
                            ],
                            "explanation": "Конструктор на всю квартиру",
                            "source_quote_id": "E02"
                        }
                    ],
                    "true_false": [],
                    "matching": []
                }"""
            )

    llm = LLMWithCrossRowParaphrase()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Преимущества и консультация по Фениксу",
            objectives=["Объяснять преимущества и особенности коллекции"],
            content="Generated prose is not evidence.",
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
        compact=True,
    )

    assert llm.calls == 1
    assert len(result.mcq) == 1
    correct_answers = {next(option.text for option in question.options if option.is_correct) for question in result.mcq}
    assert "Одна платформа на всю квартиру" in correct_answers
    assert "Конструктор на всю квартиру" not in correct_answers


@pytest.mark.asyncio
async def test_model_assessment_drops_weak_structured_questions_without_retry_or_padding() -> None:
    rows = (
        "| Материал корпуса Чикаго Нео | ЛДСП Kronospan |",
        "| Материал корпуса Феникс | МДФ Kronospan |",
        "| Материал корпуса Чикаго Стрит | массив дуба |",
        "| Материал корпуса Imperial | мебельная фанера |",
        "| Особенности Чикаго Нео | Взрослый размер и матовые торцевые ручки |",
        "| Кому рекомендовать Феникс | Кто делает несколько комнат в одном стиле |",
    )
    source = "\n".join(rows)
    evidence_ids = {quote: evidence_id for evidence_id, quote in _build_evidence_bank(source).items()}

    questions = [
        {
            "question": "Какой материал корпуса у Чикаго Нео?",
            "options": [
                {"text": "ЛДСП Kronospan", "is_correct": True},
                {"text": "МДФ Kronospan", "is_correct": False},
                {"text": "массив дуба", "is_correct": False},
                {"text": "мебельная фанера", "is_correct": False},
            ],
            "explanation": rows[0],
            "source_quote_id": evidence_ids[rows[0]],
        },
        {
            "question": "Какой размер и какие ручки указаны в описании?",
            "options": [
                {"text": "Взрослый размер и матовые торцевые ручки", "is_correct": True},
                {"text": "Компактный размер и скрытые ручки", "is_correct": False},
                {"text": "Детский размер и накладные ручки", "is_correct": False},
                {"text": "Увеличенный размер и глянцевые ручки", "is_correct": False},
            ],
            "explanation": rows[4],
            "source_quote_id": evidence_ids[rows[4]],
        },
        {
            "question": "Кому рекомендовать Феникс, если человек делает несколько комнат в одном стиле?",
            "options": [
                {"text": "Кто делает несколько комнат в одном стиле", "is_correct": True},
                {"text": "Кто оформляет одну комнату без хранения", "is_correct": False},
                {"text": "Кто выбирает разные стили для комнат", "is_correct": False},
                {"text": "Кто подбирает мебель только для офиса", "is_correct": False},
            ],
            "explanation": rows[5],
            "source_quote_id": evidence_ids[rows[5]],
        },
    ]

    class LLMWithWeakStructuredQuestions:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {"mcq": questions, "true_false": [], "matching": []},
                    ensure_ascii=False,
                )
            )

    llm = LLMWithWeakStructuredQuestions()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Сравнение коллекций",
            objectives=["Подбирать коллекцию и объяснять её характеристики"],
            content="Generated prose is not evidence.",
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
        compact=True,
    )

    assert llm.calls == 1
    assert len(result.mcq) == 1
    assert result.mcq[0].question == "Какой материал корпуса у Чикаго Нео?"


@pytest.mark.asyncio
async def test_model_assessment_keeps_lesson_without_quiz_when_all_structured_questions_are_weak() -> None:
    rows = (
        "| Особенности Чикаго Нео | Взрослый размер и матовые торцевые ручки |",
        "| Кому рекомендовать Феникс | Кто делает несколько комнат в одном стиле |",
    )
    source = "\n".join(rows)
    evidence_ids = {quote: evidence_id for evidence_id, quote in _build_evidence_bank(source).items()}
    questions = [
        {
            "question": "Какой размер и какие ручки указаны в описании?",
            "options": [
                {"text": "Взрослый размер и матовые торцевые ручки", "is_correct": True},
                {"text": "Компактный размер и скрытые ручки", "is_correct": False},
                {"text": "Детский размер и накладные ручки", "is_correct": False},
                {"text": "Увеличенный размер и глянцевые ручки", "is_correct": False},
            ],
            "explanation": rows[0],
            "source_quote_id": evidence_ids[rows[0]],
        },
        {
            "question": "Кому рекомендовать Феникс, если человек делает несколько комнат в одном стиле?",
            "options": [
                {"text": "Кто делает несколько комнат в одном стиле", "is_correct": True},
                {"text": "Кто оформляет одну комнату без хранения", "is_correct": False},
                {"text": "Кто выбирает разные стили для комнат", "is_correct": False},
                {"text": "Кто подбирает мебель только для офиса", "is_correct": False},
            ],
            "explanation": rows[1],
            "source_quote_id": evidence_ids[rows[1]],
        },
    ]

    class LLMWithOnlyWeakQuestions:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {"mcq": questions, "true_false": [], "matching": []},
                    ensure_ascii=False,
                )
            )

    llm = LLMWithOnlyWeakQuestions()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Позиционирование коллекций",
            objectives=["Подбирать коллекцию под запрос покупателя"],
            content="Generated prose is not evidence.",
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
        compact=True,
    )

    assert llm.calls == 1
    assert result.lesson_title == "Позиционирование коллекций"
    assert result.mcq == []


@pytest.mark.asyncio
async def test_course_assessment_restores_intentionally_empty_structured_quiz_without_provider_call() -> None:
    source = "| Особенности Чикаго Нео | Взрослый размер и матовые торцевые ручки |"

    class ProviderMustNotRun:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            raise AssertionError("an intentionally empty assessment checkpoint must be restored")

    llm = ProviderMustNotRun()
    result = await generate_course_assessment(
        llm,
        CourseContent(
            title="Коллекции",
            modules=[
                ModuleContent(
                    title="Ассортимент",
                    lessons=[
                        LessonContent(
                            title="Позиционирование коллекций",
                            objectives=["Подбирать коллекцию под запрос покупателя"],
                            content="Generated prose is not evidence.",
                            source_chunks=[source],
                            source_references=[],
                        )
                    ],
                )
            ],
        ),
        language="ru",
        compact=True,
        completed_assessments={(0, 0): LessonAssessment(lesson_title="Позиционирование коллекций")},
    )

    assert llm.calls == 0
    assert len(result.assessments) == 1
    assert result.assessments[0].mcq == []


@pytest.mark.asyncio
async def test_model_assessment_drops_equivalent_fact_from_another_lesson_without_padding() -> None:
    first_row = (
        "| Что это за коллекция | Интерьерная платформа Imperial: " "модульный конструктор из нескольких дизайн-серий |"
    )
    source = "\n".join(
        (
            first_row,
            "| Материал корпуса Феникс | ЛДСП Kronospan (Австрия) |",
            "| Тип ручек Чикаго Нео | металлические торцевые ручки |",
        )
    )

    class LLMWithEarlierCourseFact:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(
                content="""{
                    "mcq": [
                        {
                            "question": "Что представляет собой коллекция Imperial?",
                            "options": [
                                {"text": "модульный конструктор из нескольких дизайн-серий", "is_correct": true},
                                {"text": "готовый комплект из одной серии", "is_correct": false},
                                {"text": "отдельная линейка мягкой мебели", "is_correct": false},
                                {"text": "набор единичных предметов интерьера", "is_correct": false}
                            ],
                            "explanation": "модульный конструктор из нескольких дизайн-серий",
                            "source_quote_id": "E01"
                        },
                        {
                            "question": "Из какого материала сделан корпус Феникс?",
                            "options": [
                                {"text": "ЛДСП Kronospan (Австрия)", "is_correct": true},
                                {"text": "массив светлого дуба", "is_correct": false},
                                {"text": "берёзовая мебельная фанера", "is_correct": false},
                                {"text": "окрашенная древесная плита", "is_correct": false}
                            ],
                            "explanation": "ЛДСП Kronospan (Австрия)",
                            "source_quote_id": "E02"
                        },
                        {
                            "question": "Какие ручки используются в Чикаго Нео?",
                            "options": [
                                {"text": "металлические торцевые ручки", "is_correct": true},
                                {"text": "круглые деревянные ручки", "is_correct": false},
                                {"text": "накладные пластиковые ручки", "is_correct": false},
                                {"text": "фрезерованные скрытые ручки", "is_correct": false}
                            ],
                            "explanation": "металлические торцевые ручки",
                            "source_quote_id": "E03"
                        }
                    ],
                    "true_false": [],
                    "matching": []
                }"""
            )

    llm = LLMWithEarlierCourseFact()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Сравнение коллекций Imperial",
            objectives=["Сравнивать материалы и фурнитуру"],
            content="Generated prose is not evidence.",
            source_chunks=[source],
            source_references=[],
        ),
        language="ru",
        compact=True,
        excluded_fact_keys=frozenset(
            {
                (
                    _normalize_evidence_text(first_row),
                    _normalize_evidence_text(
                        "Интерьерная платформа Imperial: модульный конструктор из нескольких дизайн-серий"
                    ),
                )
            }
        ),
    )

    assert llm.calls == 1
    assert len(result.mcq) == 1
    assert all("Что представляет собой" not in question.question for question in result.mcq)


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
        "ЛДСП",
        "МДФ",
        "металл и ЛДСП",
        "уточнить размеры помещения",
        "согласовать оттенок",
        "обсудить нагрузку",
        "показать механизм открывания",
        "уточнить объём хранения",
        "собрать требования к высоте",
    }
    assert [len(assessment.mcq) for assessment in result.assessments] == [5, 5, 5]
    assert assessment_paths == ["tabular", "tabular", "tabular"]
    actual_options = {
        option.text for assessment in result.assessments for question in assessment.mcq for option in question.options
    }
    assert actual_options <= source_values


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
            _normalize_evidence_text(next(option.text for option in question.options if option.is_correct)),
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
        next(option.text for option in question.options if option.is_correct) for question in result.assessments[2].mcq
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
        *[{"text": distractor, "is_correct": False} for distractor in distractors],
    ]
    return [
        {
            "question": f"Что требуется для {topic}?",
            "options": options,
            "explanation": f"Материал связывает {topic} с {fact}.",
            "source_quote": source_quote,
            "source_quote_id": source_quote_id,
        }
    ] + _additional_questions()[: count - 1]


def test_contract_diagnostics_use_bounded_reason_codes():
    error = ValueError("MCQ #1: unknown source evidence id; MCQ #2: correct answer is an incomplete fragment")

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
    source = _source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления.")
    generated_intro = "В этом уроке разбираем правила. Эти правила — основа успешной работы."

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            prompt = messages[-1]["content"]
            evidence_payload = prompt.split("ALLOWED_EVIDENCE_BANK", 1)[1].split("END_ALLOWED_EVIDENCE_BANK", 1)[0]
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
            evidence_section = prompt.split("ALLOWED_EVIDENCE_BANK", 1)[1].split("END_ALLOWED_EVIDENCE_BANK", 1)[0]
            assert "Alpha" in evidence_section
            assert "Beta" in evidence_section
            assert "Gamma" in evidence_section
            preferred_section = prompt.split("PREFERRED_EVIDENCE_IDS", 1)[1].split("END_PREFERRED_EVIDENCE_IDS", 1)[0]
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
    assert all(question.question != questions[0]["question"] for question in result.mcq)


@pytest.mark.asyncio
async def test_standard_assessment_retries_an_incomplete_result():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content='{"mcq": [], "true_false": [], "matching": []}')
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

    assert result.mcq[0].source_quote == ("Выдача микрокредита выполняется после проверки заявления.")


@pytest.mark.asyncio
async def test_standard_assessment_requests_provider_structured_output():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            assert response_format is not None
            assert response_format["type"] == "json_schema"
            schema = response_format["json_schema"]["schema"]
            assert schema["properties"]["mcq"]["minItems"] == 5
            assert schema["properties"]["mcq"]["maxItems"] == 5
            assert schema["properties"]["mcq"]["items"]["properties"]["source_quote_id"]["enum"] == [
                "E01",
                "E02",
                "E03",
                "E04",
                "E05",
            ]
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
        assert question.explanation == f"В исходном материале указано: «{question.source_quote}»"


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
    assert result.mcq[0].source_quote == ("Критический приоритет — Не позднее 15 минут")


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
    assert all(max(len(option.text) for option in question.options) < len(source_quote) for question in result.mcq)


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
    assert all(option.text != "Yes" for question in result.mcq for option in question.options if option.is_correct)


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
                evidence_id = schema["properties"]["mcq"]["items"]["properties"]["source_quote_id"]["enum"][0]
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
                evidence_id = schema["properties"]["mcq"]["items"]["properties"]["source_quote_id"]["enum"][0]
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
                        {"text": f"after {correct_suffix}", "is_correct": True},
                        {"text": f"before {correct_suffix}", "is_correct": False},
                        {"text": f"during {alternative}", "is_correct": False},
                        {"text": f"without {correct_suffix}", "is_correct": False},
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
    questions.append(
        {
            "question": "When does loan delinquency occur?",
            "options": [
                {"text": "after a missed due date", "is_correct": True},
                {"text": "before a missed due date", "is_correct": False},
                {"text": "during a scheduled due date", "is_correct": False},
                {"text": "without a recorded due date", "is_correct": False},
            ],
            "explanation": "Loan delinquency occurs after a missed due date.",
            "source_quote_id": "E06",
        }
    )
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
            selected = questions[:3] if self.calls == 1 else questions[3:6]
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {
                        "mcq": selected,
                        "true_false": [],
                        "matching": [],
                    }
                )
            )

    llm = InspectingLLM()
    result = await generate_course_assessment(
        llm,
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

    assert llm.calls == 2
    assert len(result.assessments[0].mcq) == 3
    assert len(result.assessments) == 2
    assert len(result.assessments[1].mcq) == 3


@pytest.mark.asyncio
async def test_course_assessment_regenerates_invalid_restored_meta_question():
    questions = _loan_questions()
    source = " ".join(q["explanation"] for q in questions)
    restored_questions = [
        {
            **question,
            "source_quote": question["explanation"],
        }
        for question in questions
    ]
    restored_questions[0]["question"] = "How is loan approval described in the source material?"
    stale = LessonAssessment.from_dict(
        {
            "lesson_title": "Approval",
            "mcq": restored_questions,
            "true_false": [],
            "matching": [],
        }
    )

    class ValidLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
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
    regenerated: list[LessonAssessment] = []
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
                            content=source,
                            source_references=[],
                        )
                    ],
                )
            ],
        ),
        language="en",
        completed_assessments={(0, 0): stale},
        on_assessment_complete=lambda _module, _lesson, item: regenerated.append(item),
    )

    assert llm.calls == 1
    assert len(regenerated) == 1
    assert result.assessments[0].mcq[0].question == "When does loan approval occur?"
