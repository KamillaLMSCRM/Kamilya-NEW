"""Integration test validating V3 generation architecture and 4-distractor synthesis."""

import pytest

from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import DistractorCategory, RuleEntity, V3Lesson, V3Option, V3Question


@pytest.mark.asyncio
async def test_v3_lesson_and_question_contracts():
    """Verify that V3 models enforce 4 realistic options with zero binary fallbacks."""
    q = V3Question(
        question_id="q1",
        scenario_premise="Клиент обратился в филиал с просьбой продлить срок залогового билета. При проверке в 1С эксперт-оценщик видит, что билет не согласован АУП РД.",
        prompt="Какое решение обязан принять эксперт-оценщик?",
        options=(
            V3Option(
                text="Категорически отказать в пролонгации до получения официального согласования АУП РД",
                is_correct=True,
                distractor_rationale="Прямое требование п. 3 Стандартов",
            ),
            V3Option(
                text="Оформить пролонгацию на минимальный срок (до 5 дней) под личную ответственность",
                is_correct=False,
                distractor_category=DistractorCategory.PROCEDURAL_CONFUSION,
                distractor_rationale="Самовольное сокращение срока не отменяет запрет на продление",
            ),
            V3Option(
                text="Запросить устное разрешение директора филиала и продлить билет",
                is_correct=False,
                distractor_category=DistractorCategory.ROLE_CONFUSION,
                distractor_rationale="Директор филиала не заменяет согласующую роль АУП РД",
            ),
            V3Option(
                text="Перенести дату платежа в 1С без распечатки нового билета",
                is_correct=False,
                distractor_category=DistractorCategory.UNAUTHORIZED_ACTION,
                distractor_rationale="Скрытая пролонгация в учетной системе запрещена",
            ),
        ),
        explanation="Согласно п. 3 Стандартов, при отсутствии согласования АУП РД проводить пролонгацию категорически запрещается. Ни директор филиала, ни эксперт не вправе продлевать несогласованный заём.",
        rule_id="rule-prolongation-ban",
        source_quote="3. Эксперт-оценщикам категорически запрещается проводить пролонгацию по залоговому билету, в случае если микрокредит не согласован АУП РД.",
    )

    lesson = V3Lesson(
        lesson_id="lesson-prolongation",
        title="Порядок пролонгации и действия при несогласовании",
        module_title="Согласование микрокредитов",
        content="### Запрет на пролонгацию без согласования\n\nЕсли микрокредит не имеет согласования...",
        covered_rule_ids=("rule-prolongation-ban",),
        questions=(q,),
    )

    data = lesson.to_dict()
    assert data["title"] == "Порядок пролонгации и действия при несогласовании"
    assert len(data["questions"]) == 1
    opts = data["questions"][0]["options"]
    assert len(opts) == 4
    correct = [o for o in opts if o["is_correct"]]
    assert len(correct) == 1
    assert correct[0]["text"].startswith("Категорически отказать")
    # Assert distinct distractor categories
    distractor_cats = {o["distractor_category"] for o in opts if not o["is_correct"]}
    assert DistractorCategory.ROLE_CONFUSION.value in distractor_cats
    assert DistractorCategory.PROCEDURAL_CONFUSION.value in distractor_cats
    assert DistractorCategory.UNAUTHORIZED_ACTION.value in distractor_cats


@pytest.mark.asyncio
async def test_v3_pipeline_generation_mock():
    """Verify that V3GenerationPipeline correctly handles LLM responses."""
    mock_response = {
        "lesson_id": "lesson-test-1",
        "title": "Урок по регламенту",
        "module_title": "Модуль 1",
        "content": "### Введение\nПравила оценки камней...",
        "questions": [
            {
                "question_id": "q1",
                "rule_id": "rule-gemstones",
                "scenario_premise": "Эксперт осматривает изделие с бриллиантами.",
                "prompt": "По скольким параметрам проводится оценка?",
                "options": [
                    {"text": "По 7 параметрам (вес, проба, категория, чистота и др.)", "is_correct": True},
                    {"text": "Только по весу и пробе", "is_correct": False, "distractor_category": "procedural_confusion"},
                    {"text": "По усмотрению директора филиала", "is_correct": False, "distractor_category": "role_confusion"},
                    {"text": "Оценка камней не проводится", "is_correct": False, "distractor_category": "unauthorized_action"},
                ],
                "explanation": "Норма требует проверки по всем 7 пунктам.",
                "source_quote": "соответствие описанию, весу, пробе...",
            }
        ],
    }

    async def fake_invoker(messages, response_format):
        return mock_response

    pipeline = V3GenerationPipeline(fake_invoker)
    rule = RuleEntity(
        rule_id="rule-gemstones",
        section="Стандарты",
        title="Оценка камней",
        statement="Проверка по 7 параметрам",
    )
    lesson = await pipeline.generate_lesson_with_scenarios("Модуль 1", "Оценка камней", [rule])
    assert lesson.lesson_id == "lesson-test-1"
    assert len(lesson.questions) == 1
    assert len(lesson.questions[0].options) == 4
    assert lesson.questions[0].options[0].is_correct is True
