from __future__ import annotations

import json

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _parse_axis_questions


def _fixture() -> tuple[LessonDraft, SourceFact]:
    fact = SourceFact(
        "fact-1",
        "Персональные данные",
        "правило передачи",
        "Передавать персональные данные можно только через разрешённый канал.",
        "doc_id=policy;section=privacy;part=1",
    )
    lesson = LessonDraft(
        "lesson-1",
        "Безопасность",
        "Передача персональных данных",
        "Применять разрешённые каналы",
        fact.value,
        (fact.fact_id,),
        (),
        2,
    )
    return lesson, fact


def test_server_owned_axis_materializes_the_same_key_regardless_of_model_key_fields() -> None:
    lesson, fact = _fixture()
    axis = derive_assessment_axes(lesson, [fact], block_id="block-1")[0]

    authored = AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="Как следует передавать персональные данные?",
        distractors=(
            "Через любой удобный канал.",
            "Через личный мессенджер после устного согласия.",
        ),
    )
    question = materialize_assessment(axis, authored)

    assert question is not None
    assert question.correct_answer == fact.value
    assert question.fact_id == fact.fact_id
    assert question.evidence_fact_ids == (fact.fact_id,)
    assert question.options[0] == fact.value
    assert set(question.options[1:]) == set(authored.distractors)


def test_materialization_rejects_a_distractor_equivalent_to_the_server_key() -> None:
    lesson, fact = _fixture()
    axis = derive_assessment_axes(lesson, [fact], block_id="block-1")[0]
    authored = AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="Как следует передавать персональные данные?",
        distractors=(
            "  передавать персональные данные можно только через разрешенный канал. ",
            "Через любой удобный канал.",
        ),
    )

    assert materialize_assessment(axis, authored) is None


def test_axis_identity_and_key_do_not_depend_on_fact_order() -> None:
    lesson, first = _fixture()
    second = SourceFact(
        "fact-2",
        "Персональные данные",
        "исключение",
        "Срочность не отменяет правило разрешённого канала.",
        "doc_id=policy;section=privacy;part=2",
    )
    lesson = LessonDraft(
        lesson.lesson_id,
        lesson.module_title,
        lesson.title,
        lesson.objective,
        lesson.content,
        (first.fact_id, second.fact_id),
        (),
        lesson.duration_minutes,
    )

    forward = derive_assessment_axes(lesson, [first, second], block_id="block-1")
    reverse = derive_assessment_axes(lesson, [second, first], block_id="block-1")

    assert [(axis.axis_id, axis.correct_value) for axis in forward] == [
        (axis.axis_id, axis.correct_value) for axis in reverse
    ]


def test_axis_selection_follows_canonical_lesson_source_order_not_hash_order() -> None:
    lesson, first = _fixture()
    second = SourceFact(
        "fact-z",
        "Персональные данные",
        "исключение",
        "Срочность не отменяет правило разрешённого канала.",
        "doc_id=policy;section=privacy;part=2",
    )
    lesson = LessonDraft(
        lesson.lesson_id, lesson.module_title, lesson.title, lesson.objective,
        lesson.content, (second.fact_id, first.fact_id), (), lesson.duration_minutes,
    )

    axes = derive_assessment_axes(lesson, [first, second], block_id="block-1")

    assert [axis.primary_fact_id for axis in axes] == [second.fact_id, first.fact_id]


def test_initial_author_response_must_cover_every_server_selected_axis() -> None:
    lesson, first = _fixture()
    second = SourceFact(
        "fact-2",
        "Персональные данные",
        "исключение",
        "Срочность не отменяет правило разрешённого канала.",
        "doc_id=policy;section=privacy;part=2",
    )
    lesson = LessonDraft(
        lesson.lesson_id, lesson.module_title, lesson.title, lesson.objective,
        lesson.content, (first.fact_id, second.fact_id), (), lesson.duration_minutes,
    )
    axes = derive_assessment_axes(lesson, [first, second], block_id="block-1")
    partial_response = json.dumps({"questions": [{
        "axis_id": axes[0].axis_id,
        "prompt": "Как следует передавать персональные данные?",
        "distractors": ["Через любой канал.", "Через личный мессенджер."],
    }]})

    with pytest.raises(ValueError, match="assessment_axes_missing"):
        _parse_axis_questions(
            partial_response,
            axes=axes,
            maximum=len(axes),
            require_all=True,
        )

    assert _parse_axis_questions(
        json.dumps({"questions": []}),
        axes=axes,
        maximum=len(axes),
        require_all=True,
    ) == []


def test_narrative_axis_uses_one_exact_actionable_claim_not_the_whole_paragraph() -> None:
    value = (
        "Персональные данные передаются только по разрешённым каналам. "
        "Если клиент просит отправить их в личный мессенджер сотрудника, сотрудник "
        "отказывает в таком способе передачи и предлагает разрешённый канал. "
        "Срочность обращения не отменяет это правило."
    )
    fact = SourceFact(
        "fact-long",
        "Рабочие правила",
        "положение",
        value,
        "doc_id=policy;section=privacy;part=1",
    )
    lesson = LessonDraft(
        "lesson-long", "Работа", "Передача данных", "Выбрать разрешённый канал",
        value, (fact.fact_id,), (), 3,
    )

    axis = derive_assessment_axes(lesson, [fact], block_id="block-long")[0]

    assert axis.correct_value == (
        "Если клиент просит отправить их в личный мессенджер сотрудника, сотрудник "
        "отказывает в таком способе передачи и предлагает разрешённый канал."
    )
    assert axis.correct_value in value


def test_spreadsheet_axis_uses_one_exact_claim_not_the_whole_compound_cell() -> None:
    value = (
        "Спальня (шкафы и хранение), прихожая, гостиная, гардеробная. "
        "Кроватей в линейке нет."
    )
    fact = SourceFact(
        "fact-range",
        "Феникс",
        "Для каких комнат",
        value,
        "doc_id=catalog;section=Коллекции;row=3;column=2",
    )
    lesson = LessonDraft(
        "lesson-range", "Коллекции", "Феникс", "Консультировать по ассортименту",
        value, (fact.fact_id,), (), 2,
    )

    axis = derive_assessment_axes(lesson, [fact], block_id="block-range")[0]

    assert axis.correct_value == (
        "Спальня (шкафы и хранение), прихожая, гостиная, гардеробная."
    )
    assert axis.correct_value in value


def test_spreadsheet_axis_keeps_direct_first_value_before_shorter_context() -> None:
    value = (
        "Спальня и прихожая: кровати, шкафы, комоды, прикроватные тумбы, вешалки. "
        "Стыкуется с жилыми зонами той же палитры."
    )
    fact = SourceFact(
        "fact-rooms",
        "Чикаго Нео",
        "Для каких комнат",
        value,
        "doc_id=catalog;section=Коллекции;row=3;column=3",
    )
    lesson = LessonDraft(
        "lesson-rooms", "Коллекции", "Чикаго Нео", "Консультировать по ассортименту",
        value, (fact.fact_id,), (), 2,
    )

    axis = derive_assessment_axes(lesson, [fact], block_id="block-rooms")[0]

    assert axis.correct_value == (
        "Спальня и прихожая: кровати, шкафы, комоды, прикроватные тумбы, вешалки."
    )


def test_right_to_refuse_uses_a_server_owned_non_conditional_prompt() -> None:
    value = (
        "Заявитель вправе отказаться от заключения договора о предоставлении "
        "микрокредита (Залогового билета)."
    )
    fact = SourceFact(
        "fact-refusal",
        "Заключение договора",
        "право заявителя",
        value,
        "doc_id=rules;section=contract;part=1",
    )
    lesson = LessonDraft(
        "lesson-refusal", "Договор", "Права заявителя", "Применять право отказа",
        value, (fact.fact_id,), (), 2,
    )

    axis = derive_assessment_axes(lesson, [fact], block_id="block-refusal")[0]

    assert axis.required_prompt == (
        "Что вправе сделать Заявитель в отношении заключения договора о предоставлении "
        "микрокредита (Залогового билета)?"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "Залоговый билет — договор о предоставлении микрокредита и договор залога, "
            "заключаемый Ломбардом с Заявителем, Клиентом при предоставлении краткосрочного "
            "микрокредита, содержащий сведения о предмете залога и условиях предоставления "
            "микрокредита; заявление о присоединении к Стандартным условиям Договора о "
            "предоставлении микрокредита; титульный лист",
            "Залоговый билет",
        ),
        (
            "Сотрудники Ломбарда, в функциональные обязанности которых входит работа с "
            "микрокредитами, должны детально ознакомиться с настоящими Правилами, а также "
            "требованиями законодательства Республики Казахстан, регулирующими деятельность "
            "микрофинансовых организаций.",
            "Детально ознакомиться с настоящими Правилами, а также требованиями законодательства Республики Казахстан, "
            "регулирующими деятельность микрофинансовых организаций",
        ),
    ],
)
def test_lombard_axis_atomizes_observed_overlong_correct_answers(
    value: str,
    expected: str,
) -> None:
    fact = SourceFact(
        "fact-lombard-long",
        "Правила",
        "определение или обязанность",
        value,
        "doc_id=lombard;section=rules;part=1",
    )
    lesson = LessonDraft(
        "lesson-lombard-long",
        "Правила",
        "Ключевое положение",
        "Применять положение",
        value,
        (fact.fact_id,),
        (),
        3,
    )

    axis = derive_assessment_axes(lesson, [fact], block_id="block-lombard-long")[0]

    assert axis.correct_value == expected
    assert axis.correct_value.casefold() in value.casefold()
    assert len(axis.correct_value) <= 240


def test_optional_rule_gets_a_server_owned_question_form() -> None:
    fact = SourceFact(
        "fact-optional",
        "Первый ответ",
        "положение",
        "Окончательное решение в первом ответе не требуется.",
        "doc_id=policy;section=reply;part=1",
    )
    lesson = LessonDraft(
        "lesson-optional", "Обращения", "Первый ответ", "Подготовить первый ответ",
        fact.value, (fact.fact_id,), (), 2,
    )
    axis = derive_assessment_axes(lesson, [fact], block_id="block-optional")[0]
    assert axis.required_prompt == "Требуется ли окончательное решение в первом ответе?"
    question = materialize_assessment(axis, AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="Что сотрудник обязан сделать?",
        distractors=(
            "Окончательное решение требуется сразу.",
            "Первый ответ не направляется.",
        ),
    ))

    assert question is not None
    assert question.prompt == "Требуется ли окончательное решение в первом ответе?"
    assert question.kind == "true_false"
    assert question.options == (
        "Окончательное решение в первом ответе не требуется.",
        "Окончательное решение в первом ответе требуется.",
    )


@pytest.mark.parametrize(
    ("attribute", "value", "expected_prompt", "expected_answer"),
    [
        (
            "запрет",
            "Ломбарду не допускается принятие в залог: - 1) недвижимого имущества; "
            "- 2) скоропортящегося сырья, продуктов питания; - 3) арестованного имущества.",
            "Допускается ли принятие в залог скоропортящегося сырья, продуктов питания?",
            "Нет, принятие в залог скоропортящегося сырья, продуктов питания не допускается.",
        ),
        (
            "право",
            "Ломбард имеет право принимать в залог: - 1) золотые монеты; "
            "- 2) устройства сотовой связи; - 3) электротехническое оборудование.",
            "Вправе ли Ломбард принимать в залог золотые монеты?",
            "Да, Ломбард вправе принимать в залог золотые монеты.",
        ),
        (
            "срок",
            "Персональные данные подлежат уничтожению Ломбардом: "
            "- 1) по истечении срока хранения; - 2) при вступлении в законную силу "
            "решения суда; - 3) в иных установленных законом случаях.",
            "Подлежат ли персональные данные уничтожению при вступлении в законную силу решения суда?",
            "Да, персональные данные подлежат уничтожению при вступлении в законную силу решения суда.",
        ),
    ],
)
def test_list_axis_keeps_preamble_semantics_in_prompt_and_answer(
    attribute: str,
    value: str,
    expected_prompt: str,
    expected_answer: str,
) -> None:
    fact = SourceFact("f", "Правила", attribute, value, "doc_id=d;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Правила", "Применять правила", "", ("f",), (), 1)

    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]

    assert axis.required_prompt == expected_prompt
    assert axis.correct_value == expected_answer


def test_refusal_list_does_not_turn_generic_preamble_into_answer_key() -> None:
    value = (
        "Ломбард вправе отказать в предоставлении микрокредита при наличии оснований: "
        "- 1) информация заявителя недостоверна; - 2) наличие у заявителя "
        "непогашенной задолженности; - 3) необходимые документы не представлены."
    )
    fact = SourceFact("f", "Заявление", "право", value, "doc_id=d;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Отказ", "Применять основания", "", ("f",), (), 1)

    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]

    assert axis.correct_value != (
        "Ломбард вправе отказать в предоставлении микрокредита при наличии оснований"
    )
    assert "является основанием для отказа" in axis.correct_value
    assert axis.required_prompt.startswith("Является ли")


def test_negative_right_keeps_negation_in_answer_and_owns_yes_no_prompt() -> None:
    value = (
        "Ломбард не вправе требовать выплаты вознаграждения, неустойки (штрафов, пени), "
        "начисленных по истечении 90 последовательных календарных дней просрочки."
    )
    fact = SourceFact("f", "Просрочка", "запрет", value, "doc_id=d;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Просрочка", "Применять запрет", "", ("f",), (), 1)

    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]

    assert axis.required_prompt.startswith("Вправе ли Ломбард требовать")
    assert axis.correct_value.startswith("Ломбард не вправе требовать")


def test_non_admission_rule_gets_direct_server_owned_prompt() -> None:
    value = "Отказ в приеме обращений не допускается."
    fact = SourceFact("f", "Обращения", "запрет", value, "doc_id=d;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Обращения", "Принимать обращения", "", ("f",), (), 1)

    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]

    assert axis.required_prompt == "Допускается ли отказ в приеме обращений?"
    assert axis.correct_value == value


def test_open_information_rule_cannot_be_expanded_with_an_uncited_obligation() -> None:
    value = (
        "Настоящие Правила являются открытой информацией и не могут быть предметом "
        "коммерческой тайны."
    )
    fact = SourceFact("f", "Правила", "статус", value, "doc_id=d;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Статус", "Знать статус", "", ("f",), (), 1)

    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]

    assert axis.required_prompt == (
        "Являются ли настоящие Правила открытой информацией и могут ли быть предметом "
        "коммерческой тайны?"
    )
    assert axis.correct_value == value

    question = materialize_assessment(axis, AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="Может ли документ быть тайной?",
        distractors=(
            "Документ доступен только по запросу.",
            "Документ является внутренним.",
            "Документ публикуется частично.",
        ),
    ))

    assert question is not None
    assert question.kind == "true_false"
    assert question.options == (
        value,
        "Настоящие Правила не являются открытой информацией и могут быть предметом "
        "коммерческой тайны.",
    )


@pytest.mark.parametrize(
    ("value", "expected_inverse"),
    [
        (
            "Ломбард не вправе требовать выплаты вознаграждения после 90 дней просрочки.",
            "Ломбард вправе требовать выплаты вознаграждения после 90 дней просрочки.",
        ),
        (
            "Отказ в приеме обращений не допускается.",
            "Отказ в приеме обращений допускается.",
        ),
    ],
)
def test_direct_normative_yes_no_axis_uses_server_owned_binary_inverse(
    value: str,
    expected_inverse: str,
) -> None:
    fact = SourceFact("f", "Правила", "запрет", value, "doc_id=d;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Запрет", "Применять запрет", "", ("f",), (), 1)
    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]

    question = materialize_assessment(axis, AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="Что разрешено?",
        distractors=("Неверный вариант 1", "Неверный вариант 2"),
    ))

    assert question is not None
    assert question.kind == "true_false"
    assert question.options == (value, expected_inverse)


def test_prohibition_gets_a_neutral_server_owned_question_without_invented_scenario() -> None:
    fact = SourceFact(
        "fact-prohibition",
        "Защита данных",
        "запрет",
        "Персональные данные нельзя передавать в личные мессенджеры.",
        "doc_id=policy;section=privacy;part=1",
    )
    lesson = LessonDraft(
        "lesson-prohibition", "Безопасность", "Передача данных", "Соблюдать запрет",
        fact.value, (fact.fact_id,), (), 2,
    )
    axis = derive_assessment_axes(lesson, [fact], block_id="block-prohibition")[0]

    assert axis.required_prompt == (
        "Допустимо ли передавать персональные данные в личные мессенджеры?"
    )


def test_dependent_introductory_fragment_is_not_assessed_as_a_complete_fact() -> None:
    fact = SourceFact(
        "fact-dependent",
        "Решение заёмщика",
        "подтверждение",
        "Получив информацию и ознакомившись с условиями предоставления микрокредита.",
        "doc_id=policy;section=final;part=1",
    )
    lesson = LessonDraft(
        "lesson-dependent", "Заключение", "Решение", "Понимать решение",
        fact.value, (fact.fact_id,), (), 2,
    )

    assert derive_assessment_axes(lesson, [fact], block_id="block-final") == ()


def test_complete_sentence_with_leading_gerund_remains_assessable() -> None:
    fact = SourceFact(
        "fact-complete",
        "Документ",
        "обязанность",
        "Получив документ, сотрудник обязан зарегистрировать его в журнале.",
        "doc_id=policy;section=workflow;part=1",
    )
    lesson = LessonDraft(
        "lesson-complete", "Обращения", "Регистрация", "Знать порядок",
        fact.value, (fact.fact_id,), (), 2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="block-workflow")

    assert len(axes) == 1
    assert axes[0].correct_value == fact.value
