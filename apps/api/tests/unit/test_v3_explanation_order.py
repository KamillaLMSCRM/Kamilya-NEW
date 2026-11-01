"""An explanation must survive option assembly and presentation order changes."""

from dataclasses import replace

import pytest

from app.modules.ai.v3.explanation_repair import repair_order_dependent_explanations
from app.modules.ai.v3.models import V3Course, V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase
from app.modules.ai.v3.validator import has_order_dependent_feedback, validate_v3_course


@pytest.mark.parametrize("explanation", [
    "Первый дистрактор исключает ТК РК, второй ошибочно исключает эксперта.",
    "Первый вариант неверен, второй вариант нарушает регламент.",
    "В первом неверном варианте изменена единица цены.",
    "Вариант А ошибочен, а ответ 2 не соответствует правилу.",
    "Первый правильный ответ верен.",
    "Вариант (А) ошибочен.",
    "Ответ № 5 ошибочен.",
    "Выберите второй.",
    "The first distractor omits the requirement; option B is incorrect.",
])
def test_position_references_require_revision(explanation):
    assert has_order_dependent_feedback(explanation)


@pytest.mark.parametrize("explanation", [
    "Ответ с делегированием неверен: согласование проводит АУП РД.",
    "Пункт 2 устанавливает два обязательных действия.",
    "На первом этапе нужно проверить стоимость залога.",
    "Ответ в соответствии с правилом требует проверки документа.",
    "Ответ 2024 года сохраняется в архиве.",
])
def test_source_numbers_and_chronological_order_are_not_option_positions(explanation):
    assert not has_order_dependent_feedback(explanation)


def test_saved_style_positional_explanation_is_held_after_shuffling():
    variant = V3QuestionVariant(
        variant_id="v1", branch_context="", scenario_premise="Ситуация", prompt="Что делать?",
        correct_option=V3Option(text="Проверить документ", is_correct=True),
        distractor_pool=(V3Option(text="Отказать без проверки", is_correct=False),
                         V3Option(text="Согласовать без проверки", is_correct=False),
                         V3Option(text="Пропустить это действие", is_correct=False)),
        explanation="Первый дистрактор исключает проверку, второй неверен.", source_quote="Нужно проверить документ.",
    )
    case = V3ScenarioCase(case_id="c1", rule_id="r1", learning_objective="Проверка", variants=(variant,))
    lesson = V3Lesson(lesson_id="l1", title="Проверка", module_title="Модуль", content="Правило",
                      covered_rule_ids=("r1",), cases=(case,), questions=())
    course = V3Course(course_id="course", title="Курс", document_sha256="a" * 64, lessons=(lesson,))
    report = validate_v3_course(course, source_document_text="Нужно проверить документ.")
    assert any("order-dependent explanation" in item for item in report.violations)
    assert report.structural_verdict == "FAIL"


def test_question_review_receives_the_same_branch_context_as_delivered_question():
    from app.modules.ai.v3.service import _question_option_inputs

    variant = V3QuestionVariant(variant_id="v", branch_context="Филиал А", scenario_premise="Клиент",
        prompt="Что делать?", correct_option=V3Option(text="Проверить", is_correct=True),
        distractor_pool=(V3Option(text="Пропустить", is_correct=False), V3Option(text="Отказать", is_correct=False),
                         V3Option(text="Передать", is_correct=False)), explanation="Проверить.", source_quote="Правило")
    case = V3ScenarioCase(case_id="c", rule_id="r", learning_objective="Проверка", variants=(variant,))
    lesson = V3Lesson(lesson_id="l", title="t", module_title="m", content="", covered_rule_ids=("r",), cases=(case,))
    row = _question_option_inputs(lesson)[0]
    assert row[1] == variant.assemble_question(seed=111).scenario_premise
    assert "Филиал А" in row[1]


@pytest.mark.asyncio
async def test_repair_only_changes_explanation_and_needs_later_semantic_review():
    variant = V3QuestionVariant(
        variant_id="v1", branch_context="", scenario_premise="Ситуация", prompt="Что делать?",
        correct_option=V3Option(text="Проверить документ", is_correct=True),
        distractor_pool=(V3Option(text="Отказать", is_correct=False), V3Option(text="Пропустить", is_correct=False),
                         V3Option(text="Передать другому", is_correct=False)),
        explanation="Первый дистрактор ошибочен.", source_quote="Нужно проверить документ.",
    )
    case = V3ScenarioCase(case_id="c1", rule_id="r1", learning_objective="Проверка", variants=(variant,))
    lesson = V3Lesson(lesson_id="l1", title="Проверка", module_title="Модуль", content="Правило",
                      covered_rule_ids=("r1",), cases=(case,), questions=())
    calls = []

    async def invoke(messages, response_format):
        calls.append((messages, response_format))
        return {"repairs": [{"variant_id": "v1", "explanation": "Документ необходимо проверить."}]}

    lesson = replace(lesson, questions=(variant.assemble_question(seed=42),
                                       replace(variant.assemble_question(seed=7), question_id="independent")))
    repaired, changed = await repair_order_dependent_explanations(lesson, {"r1": ["Нужно проверить документ."]}, invoke,
                                                                  ("Уточнение владельца",))
    updated = repaired.cases[0].variants[0]
    assert changed and len(calls) == 1
    assert replace(updated, explanation=variant.explanation) == variant
    assert updated.explanation == "Документ необходимо проверить."
    assert repaired.questions[0].explanation == updated.explanation
    assert repaired.questions[1] == lesson.questions[1]
    assert "Уточнение владельца" in calls[0][0][1]["content"]

    async def invalid(_messages, _response_format):
        return {"repairs": [{"variant_id": "v1", "explanation": "Первый вариант верен."}]}

    unchanged, changed = await repair_order_dependent_explanations(lesson, {"r1": ["Нужно проверить документ."]}, invalid)
    assert not changed and unchanged == lesson

    duplicated = replace(lesson, cases=(replace(case, variants=(variant, variant)),))
    unchanged, changed = await repair_order_dependent_explanations(duplicated, {"r1": ["Нужно проверить документ."]}, invoke)
    assert not changed and unchanged == duplicated and len(calls) == 1

    unchanged, changed = await repair_order_dependent_explanations(lesson, {"other": ["unrelated"]}, invoke)
    assert not changed and unchanged == lesson and len(calls) == 1

    collision = replace(lesson.questions[0], prompt="Другой независимый вопрос")
    colliding_lesson = replace(lesson, questions=(collision,))
    unchanged, changed = await repair_order_dependent_explanations(
        colliding_lesson, {"r1": ["Нужно проверить документ."]}, invoke,
    )
    assert not changed and unchanged == colliding_lesson and len(calls) == 1


@pytest.mark.asyncio
async def test_worker_reviews_the_repaired_explanation_before_acceptance():
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.service import generate_v3_course_from_corpus
    from tests.unit.test_v3_partitioned_extraction import Journal, corpus

    source = "Правило первое.\n\nПравило второе."
    events = []

    class ReviewReachedError(Exception):
        pass

    async def invoke(messages, _format):
        system, user = messages[0]["content"], messages[1]["content"]
        if "Карту регламента" in system:
            target = user.split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": "r1", "section": "Общий раздел", "title": "Правило",
                               "statement": target, "source_quote": target}]}
        if "Исправь только объяснение" in system:
            events.append("repair")
            return {"repairs": [{"variant_id": "v1", "explanation": "Действие соответствует правилу."}]}
        if "независимый контролер" in system:
            assert "Действие соответствует правилу." in user
            assert "Первый дистрактор неверен." not in user
            events.append("review")
            raise ReviewReachedError()
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "c1", "rule_id": "r1", "variants": [{"variant_id": "v1",
                    "scenario_premise": "Ситуация", "prompt": "Вопрос", "correct_option": {"text": "верный 1"},
                    # The case owns only rule r1; do not cross into the sibling
                    # rule's span merely to exercise explanation repair.
                    "source_quote": "Правило первое.", "explanation": "Первый дистрактор неверен.",
                    "distractor_pool": [{"text": "ошибка 1"}, {"text": "ошибка 2"}, {"text": "ошибка 3"}]}]}]}

    with pytest.raises(ReviewReachedError):
        await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                            extraction_journal=Journal(), route_fingerprint="a" * 64)
    assert events == ["repair", "review"]
