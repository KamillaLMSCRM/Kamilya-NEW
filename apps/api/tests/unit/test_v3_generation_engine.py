"""Integration test validating V3 generation architecture and 4-distractor synthesis."""

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import (
    DistractorCategory,
    RuleEntity,
    V3Course,
    V3Lesson,
    V3Option,
    V3Question,
    V3QuestionVariant,
    V3ScenarioCase,
)
from app.modules.ai.v3.service import generate_v3_course_from_corpus


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


@pytest.mark.asyncio
async def test_v3_scenario_case_and_variant_bank():
    """Verify that multi-variant case bank supports dynamic branch context and distractor variation."""
    var_a = V3QuestionVariant(
        variant_id="case-1-var-a",
        branch_context="Филиал в Павлодаре (Группа 1)",
        scenario_premise="Клиент оформляет микрокредит на сумму 1 200 000 тенге в Павлодаре.",
        prompt="К какой категории относится микрокредит?",
        correct_option=V3Option(
            text="Ко II категории, так как для Павлодара порог составляет от 1 100 100 тенге",
            is_correct=True,
        ),
        distractor_pool=(
            V3Option(
                text="К I категории, ориентируясь на лимит Алматы до 1 400 000 тенге",
                is_correct=False,
                distractor_category=DistractorCategory.PROCEDURAL_CONFUSION,
            ),
            V3Option(
                text="Передать заявку директору филиала для утверждения льготного лимита",
                is_correct=False,
                distractor_category=DistractorCategory.ROLE_CONFUSION,
            ),
            V3Option(
                text="Отложить оформление до планового ежемесячного аудита филиала",
                is_correct=False,
                distractor_category=DistractorCategory.TIMING_VIOLATION,
            ),
            V3Option(
                text="Разбить сумму на два договора по 600 000 тенге без согласования",
                is_correct=False,
                distractor_category=DistractorCategory.UNAUTHORIZED_ACTION,
            ),
        ),
        explanation="Павлодар входит в группу 1, где II категория начинается от 1 100 100 тенге.",
        source_quote="II категория от 1 100 100 тенге...",
    )

    var_b = V3QuestionVariant(
        variant_id="case-1-var-b",
        branch_context="Филиал в Шымкенте (Группа 2)",
        scenario_premise="Клиент запрашивает 1 350 000 тенге в филиале Шымкента.",
        prompt="Каков установленный порядок определения категории?",
        correct_option=V3Option(
            text="Отнести к I категории, так как для Шымкента диапазон составляет от 700 100 до 1 400 000 тенге",
            is_correct=True,
        ),
        distractor_pool=(
            V3Option(
                text="Отнести ко II категории, ошибочно применив порог северных регионов 1 100 100 тенге",
                is_correct=False,
                distractor_category=DistractorCategory.PROCEDURAL_CONFUSION,
            ),
            V3Option(
                text="Согласовать сумму с городским акиматом вместо внутренних стандартов",
                is_correct=False,
                distractor_category=DistractorCategory.ROLE_CONFUSION,
            ),
            V3Option(
                text="Оформить заем без проверки суммы в Таблице 1",
                is_correct=False,
                distractor_category=DistractorCategory.UNAUTHORIZED_ACTION,
            ),
            V3Option(
                text="Приостановить выдачу на 5 рабочих дней до запроса в головной офис",
                is_correct=False,
                distractor_category=DistractorCategory.TIMING_VIOLATION,
            ),
        ),
        explanation="Шымкент относится ко 2 группе городов с порогом I категории до 1 400 000 тенге.",
        source_quote="от 700 100 до 1 400 000 тенге г. Шымкент...",
    )

    case = V3ScenarioCase(
        case_id="case-limits-1",
        rule_id="rule-limits-table-1",
        learning_objective="Применение региональных порогов лимитов",
        variants=(var_a, var_b),
    )

    assert len(case.variants) == 2
    # Verify that assembling question selects 1 correct + 3 distractors
    assembled_a = var_a.assemble_question(seed=123)
    assert len(assembled_a.options) == 4
    assert sum(1 for o in assembled_a.options if o.is_correct) == 1
    assert sum(1 for o in assembled_a.options if not o.is_correct) == 3

    assembled_b = var_b.assemble_question(seed=456)
    assert len(assembled_b.options) == 4
    assert sum(1 for o in assembled_b.options if o.is_correct) == 1

    # Verify that distractors formulations are completely distinct
    distractors_a = {o.text for o in var_a.distractor_pool}
    distractors_b = {o.text for o in var_b.distractor_pool}
    assert distractors_a.isdisjoint(distractors_b)


@pytest.mark.asyncio
async def test_v3_adapter_to_generation_artifacts():
    """Verify that V3 course seamlessly converts to production GenerationArtifacts for DB persistence."""
    var_a = V3QuestionVariant(
        variant_id="case-1-var-a",
        branch_context="Филиал в Павлодаре",
        scenario_premise="Клиент запрашивает микрокредит на 1 200 000 тенге.",
        prompt="Какова категория микрокредита?",
        correct_option=V3Option(text="II категория", is_correct=True),
        distractor_pool=(
            V3Option(text="I категория", is_correct=False, distractor_category=DistractorCategory.PROCEDURAL_CONFUSION),
            V3Option(text="Льготная категория", is_correct=False, distractor_category=DistractorCategory.ROLE_CONFUSION),
            V3Option(text="Без категории", is_correct=False, distractor_category=DistractorCategory.UNAUTHORIZED_ACTION),
        ),
        explanation="Порог 1 100 100 тенге.",
        source_quote="Таблица 1",
    )
    case = V3ScenarioCase(
        case_id="case-limits",
        rule_id="rule-limits",
        learning_objective="Пороги сумм",
        variants=(var_a,),
    )
    lesson = V3Lesson(
        lesson_id="lesson-limits",
        title="Лимиты выдачи микрокредитов",
        module_title="Стандарты согласования",
        content="### Текст урока\nПравила лимитов...",
        covered_rule_ids=("rule-limits",),
        cases=(case,),
        questions=(var_a.assemble_question(seed=1),),
    )
    course = V3Course(
        course_id="course-test",
        title="Стандарты согласования",
        document_sha256="abcdef1234567890",
        lessons=(lesson,),
    )

    artifacts = v3_course_to_generation_artifacts(course, source_document_ids=["doc-uuid-1"])
    assert artifacts.structure.title == "Стандарты согласования"
    assert len(artifacts.structure.modules) == 1
    assert artifacts.structure.modules[0].title == "Стандарты согласования"
    assert len(artifacts.structure.modules[0].lessons) == 1
    assert artifacts.structure.modules[0].lessons[0].title == "Лимиты выдачи микрокредитов"

    # Content verification
    assert len(artifacts.content.modules) == 1
    assert artifacts.content.modules[0].lessons[0].content == "### Текст урока\nПравила лимитов..."
    assert artifacts.content.modules[0].lessons[0].source_references == [{"doc_id": "doc-uuid-1"}]

    # Assessment verification
    assert len(artifacts.assessment.assessments) == 1
    lesson_assess = artifacts.assessment.assessments[0]
    assert lesson_assess.lesson_title == "Лимиты выдачи микрокредитов"
    assert len(lesson_assess.mcq) == 1
    mcq = lesson_assess.mcq[0]
    assert "Клиент запрашивает микрокредит" in mcq.question
    assert len(mcq.options) == 4
    assert mcq.pool_group == "case-limits"
    assert any(o.is_correct for o in mcq.options)
    assert artifacts.diagnostics["generation_engine"] == "v3_cogen"


@pytest.mark.asyncio
async def test_v3_service_generate_from_corpus():
    """Verify that generate_v3_course_from_corpus executes full pipeline on DirectSourceCorpus."""
    doc = DirectSourceDocument(
        doc_id="doc-1",
        title="Стандарты микрокредитов",
        filename="standarty.docx",
        category="regulations",
        source_revision="rev-1",
        chunks=(
            DirectSourceChunk(
                chunk_id="chunk-1",
                doc_id="doc-1",
                doc_name="standarty.docx",
                title="Таблица 1 Лимиты",
                headings=("Лимиты",),
                text="Таблица 1. Лимиты выдачи микрокредитов. От 700 100 до 1 100 000 тенге.",
                source_revision="rev-1",
                chunk_index=0,
            ),
        ),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(doc,),
        total_chars=100,
        total_chunks=1,
    )

    async def mock_client(messages, response_format):
        prompt_text = str(messages)
        if "Карту регламента" in prompt_text or "Rule Model" in prompt_text:
            return {
                "document_title": "Стандарты микрокредитов",
                "rules": [
                    {
                        "rule_id": "rule-1",
                        "section": "Лимиты",
                        "title": "Лимиты выдачи",
                        "statement": "Лимит выдачи от 700 100 тенге",
                        "conditions": ["Группа 1"],
                        "exceptions": [],
                        "actors": ["эксперт-оценщик"],
                        "timing": "",
                        "consequences": "",
                        "source_quote": "От 700 100 тенге",
                    }
                ],
            }
        else:
            return {
                "lesson_id": "lesson-1",
                "title": "Лимиты выдачи микрокредитов",
                "module_title": "Стандарты микрокредитов",
                "content": "### Обобщенный урок по лимитам\nАлгоритм действий...",
                "cases": [
                    {
                        "case_id": "case-1",
                        "rule_id": "rule-1",
                        "learning_objective": "Определение лимитов",
                        "variants": [
                            {
                                "variant_id": "case-1-var-a",
                                "branch_context": "Филиал в Павлодаре",
                                "scenario_premise": "Клиент пришел в Павлодаре.",
                                "prompt": "Какое решение принять?",
                                "correct_option": {
                                    "text": "Применить I категорию",
                                    "is_correct": True,
                                    "distractor_rationale": "Норма",
                                },
                                "distractor_pool": [
                                    {"text": "Ошибка 1", "is_correct": False, "distractor_category": "procedural_confusion"},
                                    {"text": "Ошибка 2", "is_correct": False, "distractor_category": "role_confusion"},
                                    {"text": "Ошибка 3", "is_correct": False, "distractor_category": "timing_violation"},
                                ],
                                "explanation": "Разбор ситуации",
                                "source_quote": "От 700 100 тенге",
                            }
                        ],
                    }
                ],
            }

    progress_events = []

    async def progress_cb(stage, curr, total, prov, attempt):
        progress_events.append((stage, curr, total))

    artifacts = await generate_v3_course_from_corpus(
        corpus,
        intent=CourseIntent(purpose="Обучение стандартам", audience="Оценщики", emphasis=()),
        generation_client=mock_client,
        progress_callback=progress_cb,
    )

    assert artifacts.structure.title == "Стандарты микрокредитов"
    assert len(artifacts.content.modules) >= 1
    assert len(artifacts.assessment.assessments) >= 1
    # Check that questions have 4 options and pool_group
    q = artifacts.assessment.assessments[0].mcq[0]
    assert len(q.options) == 4
    assert q.pool_group == "case-1"
    assert len(progress_events) >= 2


def test_validate_v3_course_detects_length_shortcut():
    """Verify that validate_v3_course detects when correct answer is persistently the longest option."""
    from app.modules.ai.v3.validator import validate_v3_course

    variant = V3QuestionVariant(
        variant_id="var-shortcut",
        branch_context="Филиал",
        scenario_premise="Сотрудник проверяет лимит 800 000 тенге.",
        prompt="Какое решение принять?",
        correct_option=V3Option(
            text="Это длинный правильный ответ, содержащий чрезвычайно подробное обоснование всех нормативных норм регламента",
            is_correct=True,
        ),
        distractor_pool=(
            V3Option(text="Короткая ошибка 1", is_correct=False, distractor_category=DistractorCategory.PROCEDURAL_CONFUSION),
            V3Option(text="Короткая ошибка 2", is_correct=False, distractor_category=DistractorCategory.ROLE_CONFUSION),
            V3Option(text="Короткая ошибка 3", is_correct=False, distractor_category=DistractorCategory.TIMING_VIOLATION),
        ),
        explanation="Пояснение",
        source_quote="Цитата",
    )
    case = V3ScenarioCase(case_id="case-1", rule_id="rule-1", learning_objective="Цель", variants=(variant,))
    lesson = V3Lesson(
        lesson_id="l1",
        title="Урок 1",
        module_title="Модуль 1",
        content="Текст урока",
        covered_rule_ids=("rule-1",),
        cases=(case,),
        questions=(),
    )
    course = V3Course(course_id="c1", title="Курс", document_sha256="abc", lessons=(lesson,))

    report = validate_v3_course(course, max_longest_correct_ratio=0.25)
    assert report.verdict == "FAIL"
    assert report.quality_status == "needs_review"
    assert any("Shortcut Gate" in v for v in report.violations)


def test_validate_v3_course_detects_invented_quote_and_missing_source():
    """Verify that validate_v3_course strictly fails on invented quotes and missing source text."""
    from app.modules.ai.v3.validator import validate_v3_course

    variant = V3QuestionVariant(
        variant_id="var-invented-quote",
        branch_context="Филиал",
        scenario_premise="Сотрудник оформил операцию.",
        prompt="Какое действие предпринять?",
        correct_option=V3Option(
            text="Выполнить согласование с региональным директором",
            is_correct=True,
        ),
        distractor_pool=(
            V3Option(text="Оформить операцию без согласования вопреки стандарту", is_correct=False, distractor_category=DistractorCategory.PROCEDURAL_CONFUSION),
            V3Option(text="Передать вопрос директору филиала по служебной записке", is_correct=False, distractor_category=DistractorCategory.ROLE_CONFUSION),
            V3Option(text="Отложить оформление залога до окончания плановой смены", is_correct=False, distractor_category=DistractorCategory.TIMING_VIOLATION),
        ),
        explanation="Пояснение",
        source_quote="Полностью выдуманная цитата, которой нет в тексте нормативного регламента",
    )
    case = V3ScenarioCase(case_id="case-1", rule_id="rule-1", learning_objective="Цель", variants=(variant,))
    lesson = V3Lesson(
        lesson_id="l1",
        title="Урок 1",
        module_title="Модуль 1",
        content="Текст урока",
        covered_rule_ids=("rule-1",),
        cases=(case,),
        questions=(),
    )
    course = V3Course(course_id="c1", title="Курс", document_sha256="abc", lessons=(lesson,))

    # Case A: Missing source text fails citation grounding
    report_empty = validate_v3_course(course, source_document_text="")
    assert report_empty.verdict == "FAIL"
    assert report_empty.quality_status == "needs_review"
    assert any("Source document text is empty" in v for v in report_empty.violations)

    # Case B: Invented quote fails against real source text
    report_invented = validate_v3_course(course, source_document_text="Настоящий регламент содержит совершенно другой текст.")
    assert report_invented.verdict == "FAIL"
    assert any("Citation grounding failure" in v for v in report_invented.violations)




