"""Integration test validating V3 generation architecture and 4-distractor synthesis."""

from typing import Any

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import (
    DistractorCategory,
    DocumentRuleModel,
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


def test_build_curriculum_groups_handles_colliding_titles_without_leak():
    """Verify that curriculum grouping preserves 100% of rules even when titles and auto-parts collide."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    # Section A has 7 rules (will split into Part 1 and Part 2)
    rules_a = [
        RuleEntity(rule_id=f"rule-a-{i}", section="Техника безопасности", title=f"Правило {i}", statement=f"Действие {i}")
        for i in range(1, 8)
    ]
    # Section B has the EXACT colliding name "Техника безопасности (Часть 2)" with 3 rules
    rules_b = [
        RuleEntity(rule_id=f"rule-b-{i}", section="Техника безопасности (Часть 2)", title=f"Коллизия {i}", statement=f"Действие B{i}")
        for i in range(1, 4)
    ]
    all_rules = tuple(rules_a + rules_b)
    assert len(all_rules) == 10

    rule_model = DocumentRuleModel(
        document_title="Регламент с коллизиями",
        document_sha256="fake-sha",
        rules=all_rules,
    )

    groups = _build_curriculum_groups(rule_model)

    # 1. Verify zero lost rules
    allocated_ids = {r.rule_id for g in groups for r in g.primary_rules}
    assert len(allocated_ids) == 10
    assert allocated_ids == {r.rule_id for r in all_rules}

    # 2. Verify unique group IDs
    group_ids = [g.group_id for g in groups]
    assert len(group_ids) == len(set(group_ids))
    assert len(groups) == 3  # Section A part 1 (5 rules), Section A part 2 (2 rules), Section B (3 rules)


def test_build_curriculum_groups_resolves_cross_rule_dependency_closure():
    """Verify that prerequisite conditions from other sections are preserved in dependent groups."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_prereq = RuleEntity(
        rule_id="rule-auth-required",
        section="Раздел 1: Базовые принципы",
        title="Обязательное разрешение руководителя",
        statement="Любые нестандартные операции проводятся только при личном разрешении руководителя.",
    )
    rule_dependent = RuleEntity(
        rule_id="rule-special-issuance",
        section="Раздел 2: Специальные операции",
        title="Выдача микрокредита с особыми условиями",
        statement="Эксперт оформляет выдачу в соответствии с правилом rule-auth-required при обязательном разрешении руководителя.",
    )

    rule_model = DocumentRuleModel(
        document_title="Регламент зависимостей",
        document_sha256="fake-sha",
        rules=(rule_prereq, rule_dependent),
    )

    groups = _build_curriculum_groups(rule_model)
    assert len(groups) == 2

    # Group 2 (Раздел 2) should include rule_prereq in context_prerequisite_rules
    group_2 = next(g for g in groups if g.section == "Раздел 2: Специальные операции")
    prereq_ids = {r.rule_id for r in group_2.context_prerequisite_rules}
    assert "rule-auth-required" in prereq_ids


def test_adapter_propagates_violations_and_review_flags():
    """Verify that adapter propagates violations and review requirements to GenerationArtifacts."""
    from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts

    variant = V3QuestionVariant(
        variant_id="var-1",
        branch_context="Филиал",
        scenario_premise="Ситуация",
        prompt="Вопрос?",
        correct_option=V3Option(text="Верно", is_correct=True),
        distractor_pool=(
            V3Option(text="Ошибка 1", is_correct=False, distractor_category=DistractorCategory.PROCEDURAL_CONFUSION),
            V3Option(text="Ошибка 2", is_correct=False, distractor_category=DistractorCategory.ROLE_CONFUSION),
            V3Option(text="Ошибка 3", is_correct=False, distractor_category=DistractorCategory.TIMING_VIOLATION),
        ),
        explanation="Пояснение",
        source_quote="Цитата",
    )
    case = V3ScenarioCase(case_id="c1", rule_id="r1", learning_objective="Цель", variants=(variant,))
    lesson = V3Lesson(
        lesson_id="l1",
        title="Урок 1",
        module_title="Модуль",
        content="Текст",
        covered_rule_ids=("r1",),
        cases=(case,),
        questions=(),
    )
    course = V3Course(
        course_id="c1",
        title="Курс",
        document_sha256="abc",
        lessons=(lesson,),
        quality_verdict="needs_review",
        validation_report={
            "verdict": "FAIL",
            "quality_status": "needs_review",
            "violations": ["Critical semantic gap detected: requires methodologist signoff"],
        },
    )

    artifacts = v3_course_to_generation_artifacts(course)
    assert artifacts.diagnostics["requires_source_review"] is True
    assert "Critical semantic gap detected: requires methodologist signoff" in artifacts.content.source_warnings
    assert artifacts.content.modules[0].lessons[0].source_validation_status == "needs_review"


def test_multi_level_transitive_dependency_closure():
    """Verify arbitrary-depth dependency closure: Rule 3 -> Rule 2 -> Rule 1 brings all prerequisites into context."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_1 = RuleEntity(
        rule_id="r1",
        section="Раздел 1: Базовые условия",
        title="Пункт 1: Обязательная аутентификация",
        statement="Все операции требуют двухфакторной аутентификации.",
    )
    rule_2 = RuleEntity(
        rule_id="r2",
        section="Раздел 2: Промежуточный регламент",
        title="Пункт 2: Подтверждение лимитов",
        statement="Проверка лимита выполняется строго по правилу r1 перед выдачей.",
    )
    rule_3 = RuleEntity(
        rule_id="r3",
        section="Раздел 3: Финальное оформление",
        title="Пункт 3: Закрытие сделки",
        statement="Финальное оформление проводится в соответствии с r2 и формирует договор.",
    )

    rule_model = DocumentRuleModel(
        document_title="Многоуровневый регламент",
        document_sha256="fake-sha-transitive",
        rules=(rule_1, rule_2, rule_3),
    )

    groups = _build_curriculum_groups(rule_model)
    group_3 = next(g for g in groups if g.section == "Раздел 3: Финальное оформление")
    prereq_ids = {r.rule_id for r in group_3.context_prerequisite_rules}

    # Transitive closure must contain both r2 (direct) and r1 (indirect prerequisite)
    assert "r2" in prereq_ids, "Direct dependency r2 missing from Group 3 context"
    assert "r1" in prereq_ids, "Indirect transitive prerequisite r1 missing from Group 3 context"


def test_boundary_safe_rule_id_matching():
    """Verify that rule ID matching uses word boundaries so 'r1' does NOT falsely match inside 'r10'."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_1 = RuleEntity(
        rule_id="r1",
        section="Раздел 1",
        title="Базовое правило 1",
        statement="Условие 1.",
    )
    rule_10 = RuleEntity(
        rule_id="r10",
        section="Раздел 10",
        title="Правило 10",
        statement="Условие 10.",
    )
    rule_dependent = RuleEntity(
        rule_id="r20",
        section="Раздел 20",
        title="Правило 20",
        statement="Данная операция выполняется исключительно в соответствии с r10 и никакими иными.",
    )

    rule_model = DocumentRuleModel(
        document_title="Проверка границ ID",
        document_sha256="fake-sha-boundary",
        rules=(rule_1, rule_10, rule_dependent),
    )

    groups = _build_curriculum_groups(rule_model)
    group_20 = next(g for g in groups if g.section == "Раздел 20")
    prereq_ids = {r.rule_id for r in group_20.context_prerequisite_rules}

    assert "r10" in prereq_ids, "Target dependency r10 should be resolved"
    assert "r1" not in prereq_ids, "False positive! 'r1' matched inside substring 'r10'"


def test_structured_clause_reference_resolution_and_ambiguity():
    """Verify resolution of natural clause references (e.g. 'пункт 2') and detection of ambiguous cross-section references."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_sec1_p2 = RuleEntity(
        rule_id="rule-s1-p2",
        section="Раздел 1: Прием залогов",
        title="Пункт 2: Порядок взвешивания изделий",
        statement="Взвешивание производится на поверенных весах.",
    )
    rule_sec2_p2 = RuleEntity(
        rule_id="rule-s2-p2",
        section="Раздел 2: Оценка драгоценных металлов",
        title="Пункт 2: Определение пробы",
        statement="Определение пробы проводится реактивами.",
    )
    rule_ambiguous_ref = RuleEntity(
        rule_id="rule-ambiguous",
        section="Раздел 3: Исполнение сделки",
        title="Завершение операции",
        statement="Сотрудник обязан действовать согласно пункту 2.",
    )

    rule_model = DocumentRuleModel(
        document_title="Регламент ломбарда с пунктом 2",
        document_sha256="fake-sha-clauses",
        rules=(rule_sec1_p2, rule_sec2_p2, rule_ambiguous_ref),
    )

    groups = _build_curriculum_groups(rule_model)
    group_3 = next(g for g in groups if g.section == "Раздел 3: Исполнение сделки")

    # Ambiguity check: both candidates included in context, and unresolved_dependencies flags the ambiguity
    prereq_ids = {r.rule_id for r in group_3.context_prerequisite_rules}
    assert "rule-s1-p2" in prereq_ids
    assert "rule-s2-p2" in prereq_ids
    assert any("Неоднозначная ссылка на пункт '2'" in u for u in group_3.unresolved_dependencies)


def test_rule_sanitization_and_zero_rule_leak_invariants():
    """Verify rule ID deduplication and that zero rules are lost even when duplicates or empty IDs are supplied."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_dup_1 = RuleEntity(
        rule_id="dup-id",
        section="Раздел 1",
        title="Правило 1",
        statement="Текст 1",
    )
    rule_dup_2 = RuleEntity(
        rule_id="dup-id",
        section="Раздел 1",
        title="Правило 2 с дублирующимся ID",
        statement="Текст 2",
    )
    rule_empty_id = RuleEntity(
        rule_id="",
        section="Раздел 2",
        title="Правило с пустым ID",
        statement="Текст 3",
    )

    rule_model = DocumentRuleModel(
        document_title="Грязный импорт правил",
        document_sha256="fake-sha-dedup",
        rules=(rule_dup_1, rule_dup_2, rule_empty_id),
    )

    groups = _build_curriculum_groups(rule_model)
    all_allocated_rules = [r for g in groups for r in g.primary_rules]

    # Exactly 3 rules must be present
    assert len(all_allocated_rules) == 3
    ids = [r.rule_id for r in all_allocated_rules]
    # All IDs must be unique and non-empty
    assert len(ids) == len(set(ids))
    assert all(len(i) > 0 for i in ids)


@pytest.mark.asyncio
async def test_critic_defect_propagation_to_violations_and_artifacts():
    """Verify that critic review defects (such as door open vs closed) are propagated directly into violations."""
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.service import generate_v3_course_from_corpus

    chunk = DirectSourceChunk(
        chunk_id="chk-1",
        doc_id="doc-safety-1",
        doc_name="safety.txt",
        title="Безопасность",
        headings=("Безопасность",),
        text="Регламент безопасности. Сотрудник обязан закрыть дверь сейфовой комнаты на ключ.",
        source_revision="rev-1",
        chunk_index=0,
    )
    doc = DirectSourceDocument(
        doc_id="doc-safety-1",
        title="Регламент безопасности",
        filename="safety.txt",
        category="regulations",
        source_revision="rev-1",
        chunks=(chunk,),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-safety",
        documents=(doc,),
        total_chars=100,
        total_chunks=1,
    )

    call_count = 0

    async def mock_llm_client(messages: list[dict[str, str]], response_format: Any = None) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1

        # Step 1: Rule extraction
        if call_count == 1:
            return {
                "document_title": "Регламент безопасности",
                "document_sha256": "fake-sha",
                "overview": "Обзор",
                "rules": [
                    {
                        "rule_id": "rule-door-lock",
                        "section": "Безопасность",
                        "title": "Блокировка двери",
                        "statement": "Сотрудник обязан закрыть дверь сейфовой комнаты на ключ.",
                        "conditions": [],
                        "exceptions": [],
                        "actors": ["Сотрудник"],
                        "timing": "По окончании дня",
                        "consequences": "Дисциплинарная ответственность",
                        "source_quote": "Сотрудник обязан закрыть дверь сейфовой комнаты на ключ.",
                    }
                ],
            }

        # Step 2: Generation (Hallucinating: says 'открыть дверь')
        if call_count == 2:
            return {
                "lesson_id": "lesson-door-1",
                "title": "Урок по безопасности: Двери сейфа",
                "content": "Сотрудник обязан открыть дверь сейфовой комнаты для проветривания.",
                "covered_rule_ids": ["rule-door-lock"],
                "cases": [
                    {
                        "case_id": "case-door-1",
                        "rule_id": "rule-door-lock",
                        "learning_objective": "Порядок действий с дверью сейфа",
                        "variants": [
                            {
                                "variant_id": "var-door-1",
                                "branch_context": "Филиал №1",
                                "scenario_premise": "Рабочий день завершен.",
                                "prompt": "Что обязан сделать сотрудник?",
                                "correct_option": {
                                    "text": "Открыть дверь сейфа для проветривания",
                                    "is_correct": True,
                                },
                                "distractor_pool": [
                                    {
                                        "text": "Закрыть дверь на все замки и опечатать",
                                        "is_correct": False,
                                        "distractor_category": "procedural_confusion",
                                    },
                                    {
                                        "text": "Оставить ключ в замке двери сейфа",
                                        "is_correct": False,
                                        "distractor_category": "unauthorized_action",
                                    },
                                    {
                                        "text": "Позвонить директору для консультации",
                                        "is_correct": False,
                                        "distractor_category": "role_confusion",
                                    },
                                ],
                                "explanation": "Проветривание необходимо.",
                                "source_quote": "Сотрудник обязан закрыть дверь сейфовой комнаты на ключ.",
                            }
                        ],
                    }
                ],
            }

        # Step 3: Critic Review flags contradiction
        return {
            "verdict": "FAIL",
            "defects": [
                "Критическое смысловое искажение: источник требует закрыть дверь на ключ, а урок предписывает открыть для проветривания."
            ],
            "confidence": 1.0,
        }

    intent = CourseIntent(audience="Сотрудники", purpose="Безопасность", emphasis=("Двери",))
    artifacts = await generate_v3_course_from_corpus(
        corpus=corpus,
        intent=intent,
        generation_client=mock_llm_client,
    )

    # Invariants:
    # 1. Critic review defect must be propagated into diagnostics violations
    assert any("Критическое смысловое искажение" in v for v in artifacts.diagnostics["violations"])
    # 2. Defect must be in content.source_warnings
    assert any("Критическое смысловое искажение" in w for w in artifacts.content.source_warnings)
    # 3. Requires source review must be True
    assert artifacts.diagnostics["requires_source_review"] is True
    # 4. Overall quality verdict must NOT be verified
    assert artifacts.diagnostics["quality_verdict"] != "verified"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "critic_response,expected_phrase",
    [
        ({"verdict": "FAIL", "defects": []}, "с вердиктом FAIL"),
        ({"verdict": "UNKNOWN"}, "UNKNOWN"),
        ({"verdict": "NEEDS_REVISION"}, "NEEDS_REVISION"),
        ({}, "UNKNOWN"),
    ],
)
async def test_critic_negative_or_unknown_verdict_fails_even_without_defects(
    critic_response: dict[str, Any],
    expected_phrase: str,
):
    """Verify Point 1: Negative, unknown or empty critic responses CANNOT result in PASS or empty violations."""
    chunk = DirectSourceChunk(
        chunk_id="chk-1",
        doc_id="doc-crit-1",
        doc_name="crit.txt",
        title="Регламент",
        headings=("Раздел 1",),
        text="Сотрудник обязан соблюдать график работы с 09:00 до 18:00.",
        source_revision="rev-1",
        chunk_index=0,
    )
    doc = DirectSourceDocument(
        doc_id="doc-crit-1",
        title="Регламент",
        filename="crit.txt",
        category="regulations",
        source_revision="rev-1",
        chunks=(chunk,),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-crit",
        documents=(doc,),
        total_chars=100,
        total_chunks=1,
    )

    call_count = 0

    async def mock_llm(messages: list[dict[str, str]], response_format: Any = None) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "document_title": "Регламент",
                "document_sha256": "fake-sha",
                "overview": "Обзор",
                "rules": [
                    {
                        "rule_id": "r-schedule",
                        "section": "Регламент",
                        "title": "График",
                        "statement": "Сотрудник обязан соблюдать график работы с 09:00 до 18:00.",
                        "conditions": [],
                        "exceptions": [],
                        "actors": ["Сотрудник"],
                        "timing": "Ежедневно",
                        "consequences": "Замечание",
                        "source_quote": "Сотрудник обязан соблюдать график работы с 09:00 до 18:00.",
                    }
                ],
            }
        if call_count == 2:
            return {
                "lesson_id": "l-schedule-1",
                "title": "Урок по графику",
                "content": "Соблюдайте рабочий график с 09:00 до 18:00.",
                "covered_rule_ids": ["r-schedule"],
                "cases": [
                    {
                        "case_id": "c-1",
                        "rule_id": "r-schedule",
                        "learning_objective": "Знание графика",
                        "variants": [
                            {
                                "variant_id": "v-1",
                                "branch_context": "Филиал",
                                "scenario_premise": "Рабочий день",
                                "prompt": "Каков график?",
                                "correct_option": {"text": "С 09:00 до 18:00", "is_correct": True},
                                "distractor_pool": [
                                    {"text": "С 08:00 до 17:00", "is_correct": False, "distractor_category": "timing_violation"},
                                    {"text": "С 10:00 до 19:00", "is_correct": False, "distractor_category": "timing_violation"},
                                    {"text": "В свободном режиме", "is_correct": False, "distractor_category": "unauthorized_action"},
                                ],
                                "explanation": "По регламенту.",
                                "source_quote": "Сотрудник обязан соблюдать график работы с 09:00 до 18:00.",
                            }
                        ],
                    }
                ],
            }
        # Step 3: Critic returns test response (FAIL with empty defects, UNKNOWN, NEEDS_REVISION, or {})
        return critic_response

    intent = CourseIntent(audience="Сотрудники", purpose="График", emphasis=("Время",))
    artifacts = await generate_v3_course_from_corpus(corpus=corpus, intent=intent, generation_client=mock_llm)

    # Invariants:
    # 1. Verdict must be FAIL, NEVER PASS
    assert artifacts.diagnostics["validation_report"]["verdict"] == "FAIL"
    # 2. Violations must contain the expected explanation
    violations = artifacts.diagnostics["violations"]
    assert any(expected_phrase in v for v in violations), f"Expected '{expected_phrase}' in violations: {violations}"
    # 3. Source warnings in content must also be populated
    assert len(artifacts.content.source_warnings) > 0
    # 4. Review is required
    assert artifacts.diagnostics["requires_source_review"] is True


@pytest.mark.asyncio
async def test_unverified_rule_quotes_flagged_and_isolated():
    """Verify Point 2: Rule quotes invented by the model are detected against full_text and flagged as violations."""
    chunk = DirectSourceChunk(
        chunk_id="chk-auth-1",
        doc_id="doc-auth-1",
        doc_name="auth.txt",
        title="Оригинал",
        headings=("Раздел 1",),
        text="Подлинный текст регламента содержит только это предложение.",
        source_revision="rev-1",
        chunk_index=0,
    )
    doc = DirectSourceDocument(
        doc_id="doc-auth-1",
        title="Оригинал",
        filename="auth.txt",
        category="regulations",
        source_revision="rev-1",
        chunks=(chunk,),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-auth",
        documents=(doc,),
        total_chars=100,
        total_chunks=1,
    )

    passed_source_fragments: list[str] = []
    call_count = 0

    async def mock_llm_hallucinating_quotes(messages: list[dict[str, str]], response_format: Any = None) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "document_title": "Оригинал",
                "document_sha256": "fake-sha",
                "overview": "Обзор",
                "rules": [
                    {
                        "rule_id": "r-fake-quote",
                        "section": "Раздел 1",
                        "title": "Правило с выдуманной цитатой",
                        "statement": "Сотрудник делает что-то выдуманное.",
                        "conditions": [],
                        "exceptions": [],
                        "actors": [],
                        "timing": "",
                        "consequences": "",
                        "source_quote": "Выдуманная цитата которой вообще нет в подлинном тексте документа",
                    }
                ],
            }
        if call_count == 2:
            return {
                "lesson_id": "l-1",
                "title": "Урок",
                "content": "Текст",
                "covered_rule_ids": ["r-fake-quote"],
                "cases": [
                    {
                        "case_id": "c-1",
                        "rule_id": "r-fake-quote",
                        "learning_objective": "Цель",
                        "variants": [
                            {
                                "variant_id": "v-1",
                                "branch_context": "Ф",
                                "scenario_premise": "С",
                                "prompt": "В?",
                                "correct_option": {"text": "Ответ", "is_correct": True},
                                "distractor_pool": [
                                    {"text": "Ош 1", "is_correct": False, "distractor_category": "role_confusion"},
                                    {"text": "Ош 2", "is_correct": False, "distractor_category": "role_confusion"},
                                    {"text": "Ош 3", "is_correct": False, "distractor_category": "role_confusion"},
                                ],
                                "explanation": "П",
                                "source_quote": "Подлинный текст регламента содержит только это предложение.",
                            }
                        ],
                    }
                ],
            }
        # Step 3: Critic Review
        for m in messages:
            if "ПРЯМЫЕ ЦИТАТЫ ИЗ ОРИГИНАЛА ДОКУМЕНТА" in m["content"]:
                passed_source_fragments.append(m["content"])
        return {"verdict": "PASS", "defects": []}

    intent = CourseIntent(audience="А", purpose="П", emphasis=())
    artifacts = await generate_v3_course_from_corpus(corpus=corpus, intent=intent, generation_client=mock_llm_hallucinating_quotes)

    # Invariants:
    # 1. Unverified quote violation must be detected
    violations = artifacts.diagnostics["violations"]
    assert any("Неподтвержденная цитата в правиле r-fake-quote" in v for v in violations)
    # 2. It must be explicitly tagged as unverified in prompt passed to critic
    assert any("НЕВЕРИФИЦИРОВАНО" in frag for frag in passed_source_fragments)
    # 3. Overall verdict must be FAIL
    assert artifacts.diagnostics["validation_report"]["verdict"] == "FAIL"


def test_collision_free_id_sanitization_with_preexisting_patterns():
    """Verify Point 3: Sanitization avoids collision even with tricky preexisting suffix patterns like ['x', 'x-003', 'x']."""
    from app.modules.ai.v3.service import _sanitize_rules

    rules = (
        RuleEntity(rule_id="x", section="S1", title="T1", statement="S1"),
        RuleEntity(rule_id="x-003", section="S1", title="T2", statement="S2"),
        RuleEntity(rule_id="x", section="S1", title="T3", statement="S3"),
    )

    sanitized, raw_to_rules = _sanitize_rules(rules)
    allocated_ids = [r.rule_id for r in sanitized]

    # Exactly 3 rules, all distinct
    assert len(allocated_ids) == 3
    assert len(allocated_ids) == len(set(allocated_ids))
    # "x" and "x-003" should be preserved, and duplicate "x" allocated a non-colliding suffix (e.g. "x-001" or "x-002")
    assert "x" in allocated_ids
    assert "x-003" in allocated_ids
    third_id = next(i for i in allocated_ids if i not in ("x", "x-003"))
    assert third_id != "x-003"


def test_ambiguous_reference_to_duplicated_initial_raw_id():
    """Verify Point 4: Referencing an initial duplicate raw ID is treated as ambiguous and not silently bound to first rule."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_dup_1 = RuleEntity(rule_id="dup", section="Раздел 1", title="Правило 1", statement="Условие 1")
    rule_dup_2 = RuleEntity(rule_id="dup", section="Раздел 2", title="Правило 2", statement="Условие 2")
    rule_referencing = RuleEntity(
        rule_id="r-caller",
        section="Раздел 3",
        title="Правило 3",
        statement="Сотрудник обязан действовать согласно правилу dup.",
    )

    rule_model = DocumentRuleModel(
        document_title="Дубликаты",
        document_sha256="fake-sha",
        rules=(rule_dup_1, rule_dup_2, rule_referencing),
    )

    groups = _build_curriculum_groups(rule_model)
    group_3 = next(g for g in groups if g.section == "Раздел 3")

    # Ambiguity check:
    # 1. Unresolved dependencies must flag the ambiguous reference to "dup"
    assert any("Неоднозначная ссылка на дублирующийся идентификатор 'dup'" in u for u in group_3.unresolved_dependencies)
    # 2. Both duplicate rules must be pulled into context prerequisites so no information is lost
    prereq_ids = {r.rule_id for r in group_3.context_prerequisite_rules}
    assert len(prereq_ids) == 2


def test_compound_hierarchical_reference_resolution():
    """Verify Point 5: Compound reference 'пункт 2 раздела 4' binds to Section 4 clause 2, not current section clause 2."""
    from app.modules.ai.v3.service import _build_curriculum_groups

    rule_sec1_p2 = RuleEntity(
        rule_id="r-s1-p2",
        section="Раздел 1: Базовые стандарты",
        title="Пункт 2: Порядок выдачи",
        statement="Выдача в базовом порядке.",
    )
    rule_sec4_p2 = RuleEntity(
        rule_id="r-s4-p2",
        section="Раздел 4: Пролонгация микрокредитов",
        title="Пункт 2: Продление залога",
        statement="Продление осуществляется только при уплате вознаграждения.",
    )
    rule_caller = RuleEntity(
        rule_id="r-caller-compound",
        section="Раздел 1: Базовые стандарты",
        title="Особое условие пролонгации",
        statement="При обращении клиента действовать согласно пункту 2 раздела 4.",
    )

    rule_model = DocumentRuleModel(
        document_title="Составные ссылки",
        document_sha256="fake-sha",
        rules=(rule_sec1_p2, rule_sec4_p2, rule_caller),
    )

    groups = _build_curriculum_groups(rule_model)
    group_1 = next(g for g in groups if g.section == "Раздел 1: Базовые стандарты")
    prereq_ids = {r.rule_id for r in group_1.context_prerequisite_rules}

    # Invariants:
    # 1. Must bind to Section 4 clause 2 (r-s4-p2)
    assert "r-s4-p2" in prereq_ids
    # 2. Must NOT bind to current section's clause 2 as dependency
    assert "r-s1-p2" not in prereq_ids
    # 3. Section 4 should not be flagged as missing/unresolved
    assert not any("раздела '4'" in u and "Неразрешенная" in u for u in group_1.unresolved_dependencies)


def test_end_to_end_source_review_persistence_and_invariants():
    """Verify Point 6: Full user chain where violations preserve needs_review across pipeline artifacts and storage."""
    from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts

    variant = V3QuestionVariant(
        variant_id="v-1",
        branch_context="Филиал",
        scenario_premise="Ситауция",
        prompt="Вопрос?",
        correct_option=V3Option(text="Верно", is_correct=True),
        distractor_pool=(
            V3Option(text="Ош 1", is_correct=False, distractor_category=DistractorCategory.PROCEDURAL_CONFUSION),
            V3Option(text="Ош 2", is_correct=False, distractor_category=DistractorCategory.ROLE_CONFUSION),
            V3Option(text="Ош 3", is_correct=False, distractor_category=DistractorCategory.TIMING_VIOLATION),
        ),
        explanation="Пояснение",
        source_quote="Цитата",
    )
    case = V3ScenarioCase(case_id="c-1", rule_id="r-1", learning_objective="Цель", variants=(variant,))
    lesson = V3Lesson(
        lesson_id="l-1",
        title="Урок 1",
        module_title="Модуль 1",
        content="Текст урока",
        covered_rule_ids=("r-1",),
        cases=(case,),
        questions=(),
    )
    course = V3Course(
        course_id="c-1",
        title="Курс с замечанием",
        document_sha256="abc12345",
        lessons=(lesson,),
        quality_verdict="needs_review",
        validation_report={
            "verdict": "FAIL",
            "quality_status": "needs_review",
            "violations": ["Семантический дефект: искажено правило закрытия двери"],
        },
    )

    artifacts = v3_course_to_generation_artifacts(course)

    # Invariants for user chain:
    # 1. Lesson content status is needs_review
    assert artifacts.content.modules[0].lessons[0].source_validation_status == "needs_review"
    assert artifacts.content.modules[0].lessons[0].requires_source_review() is True
    # 2. Source warnings contain defect
    assert "Семантический дефект: искажено правило закрытия двери" in artifacts.content.source_warnings
    # 3. Overall requires_source_review is True
    assert artifacts.diagnostics["requires_source_review"] is True







