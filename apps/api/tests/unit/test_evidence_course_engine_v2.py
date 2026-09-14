from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.modules.ai.evidence_engine import CourseIntent, EvidenceCourseEngine
from app.modules.ai.evidence_engine.adapters import narrative_document_from_pages
from app.modules.ai.evidence_engine.models import SourceDocument, SourceFact, SourceSection


def _narrative_source(*facts: str) -> SourceDocument:
    return SourceDocument(
        source_id="policy",
        title="Правила обслуживания клиентов",
        kind="narrative",
        sections=(
            SourceSection(
                section_id="policy:section:1",
                title="Рассмотрение заявлений",
                role="primary",
                facts=tuple(
                    SourceFact(
                        fact_id=f"policy:fact:{index}",
                        subject="Рассмотрение заявлений",
                        attribute="правило",
                        value=value,
                        source_locator=f"page=1;sentence={index}",
                    )
                    for index, value in enumerate(facts, start=1)
                ),
            ),
        ),
    )


def test_small_source_is_not_padded_to_a_fixed_lesson_or_question_quota() -> None:
    source = _narrative_source(
        "Заявление рассматривается в течение пятнадцати рабочих дней.",
        "Сотрудник проверяет полноту представленных документов.",
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    assert len(result.course.lessons) == 1
    assert len(result.assessment.questions) <= 2
    assert result.evaluation.quota_padding_count == 0


def test_lesson_content_does_not_repeat_the_outer_lesson_heading() -> None:
    source = _narrative_source(
        "Сотрудник проверяет полноту представленных документов.",
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    assert len(result.course.lessons) == 1
    assert not result.course.lessons[0].content.startswith("## ")
    assert result.course.lessons[0].content.startswith("### Подтверждённые сведения")


def test_lessons_and_questions_share_the_same_admitted_fact_ids() -> None:
    source = _narrative_source(
        "Заявление рассматривается в течение 15 рабочих дней.",
        "Уведомление направляется не позднее 30 календарных дней.",
        "Ответ на короткий запрос готовится в течение 3 рабочих дней.",
    )

    result = EvidenceCourseEngine().generate_from_document(source)
    lesson_fact_ids = {
        fact_id for lesson in result.course.lessons for fact_id in lesson.fact_ids
    }

    assert lesson_fact_ids
    assert all(question.fact_id in lesson_fact_ids for question in result.assessment.questions)
    assert all(
        question.lesson_id
        == next(
            lesson.lesson_id
            for lesson in result.course.lessons
            if question.fact_id in lesson.fact_ids
        )
        for question in result.assessment.questions
    )


def test_question_deduplication_is_fact_based_and_order_independent() -> None:
    duplicate = "Жалоба рассматривается в течение тридцати календарных дней."
    first = _narrative_source(duplicate, duplicate, "Ответ направляется клиенту письменно.")
    second = _narrative_source("Ответ направляется клиенту письменно.", duplicate, duplicate)

    first_result = EvidenceCourseEngine().generate_from_document(first)
    second_result = EvidenceCourseEngine().generate_from_document(second)

    assert first_result.semantic_fingerprint == second_result.semantic_fingerprint
    assert first_result.evaluation.duplicate_fact_count == 1
    assert second_result.evaluation.duplicate_fact_count == 1


def test_repeated_runs_have_stable_semantic_fingerprint() -> None:
    source = _narrative_source(
        "Клиент вправе получить полную информацию об условиях микрокредита.",
        "Ломбард обеспечивает конфиденциальность сведений о клиенте.",
        "Обращение регистрируется в день поступления.",
    )

    fingerprints = {
        EvidenceCourseEngine().generate_from_document(source, simulation_seed=seed).semantic_fingerprint
        for seed in range(5)
    }

    assert len(fingerprints) == 1


def test_xlsx_primary_matrix_drives_curriculum_and_catalog_is_supporting(tmp_path: Path) -> None:
    workbook = Workbook()
    primary = workbook.active
    primary.title = "Коллекции"
    primary.append(["Поле", "Феникс", "Чикаго Нео", "Чикаго Стрит"])
    primary.append(["Назначение", "Для хранения", "Для спальни", "Для прихожей"])
    primary.append(["Материал", "ЛДСП", "ЛДСП и металл", "ЛДСП"])
    primary.append(["Цвета", "Белый и графит", "Кашемир", "Бетон"])
    catalog = workbook.create_sheet("Феникс и Чикаго")
    catalog.append(["Артикул", "Наименование", "Вес", "Описание"])
    for index in range(80):
        catalog.append(
            [f"SKU-{index:03d}", f"Система Феникс модуль {index}", index + 1, "Карточка товара"]
        )
    source_path = tmp_path / "catalog.xlsx"
    workbook.save(source_path)

    result = EvidenceCourseEngine().generate(source_path, intent=CourseIntent())

    lesson_titles = {lesson.title for lesson in result.course.lessons}
    assert any("Феникс" in title for title in lesson_titles)
    assert any("Чикаго Нео" in title for title in lesson_titles)
    assert any("Чикаго Стрит" in title for title in lesson_titles)
    assert not any("SKU" in title or "Артикул" in title for title in lesson_titles)
    assert result.document_plan.primary_sections == ("Коллекции",)
    assert result.document_plan.supporting_sections == ("Феникс и Чикаго",)
    assert result.document_plan.supporting_fact_count > 0
    assert any(plan.supporting_fact_ids for plan in result.evidence_plan)


def test_safe_assessment_omits_question_when_compatible_distractors_do_not_exist() -> None:
    source = _narrative_source(
        "Ломбард обеспечивает конфиденциальность сведений о клиенте.",
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    assert len(result.course.lessons) == 1
    assert result.assessment.questions == ()
    assert result.evaluation.warnings == ("assessment_empty_no_safe_questions",)
    assert result.evaluation.unsupported_claim_count == 0


def test_narrative_questions_mask_exact_values_and_use_only_sourced_distractors() -> None:
    source = _narrative_source(
        "Заявление рассматривается в течение 15 рабочих дней.",
        "Уведомление направляется не позднее 30 календарных дней.",
        "Ответ на короткий запрос готовится в течение 3 рабочих дней.",
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    assert len(result.assessment.questions) == 3
    assert len({question.prompt for question in result.assessment.questions}) == 3
    assert all("_____" in question.prompt for question in result.assessment.questions)
    sourced_values = {"15 рабочих дней", "30 календарных дней", "3 рабочих дней"}
    assert all(set(question.options) == sourced_values for question in result.assessment.questions)


def test_narrative_options_do_not_include_equivalent_numeric_spellings() -> None:
    source = _narrative_source(
        "Первое уведомление направляется в течение 30 (тридцати) календарных дней.",
        "Второе уведомление направляется в течение тридцати календарных дней.",
        "Ответ направляется в течение 15 рабочих дней.",
        "Короткое сообщение направляется в течение семи дней.",
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    for question in result.assessment.questions:
        rendered = " | ".join(question.options).casefold()
        assert not (
            "30 (тридцати) календарных дней" in rendered
            and "тридцати календарных дней" in rendered
        )


def test_narrative_adapter_joins_wrapped_clauses_and_keeps_major_section_scope(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "rules.pdf"
    source_path.write_bytes(b"immutable-test-source")
    document = narrative_document_from_pages(
        path=source_path,
        pages=[
            "1. ОБЩИЕ ПОЛОЖЕНИЯ\n"
            "1. Настоящие правила определяют порядок предоставления\n"
            "микрокредитов физическим лицам под залог имущества.\n"
            "2. Правила предоставляются клиенту по первому требованию.",
            "2. ПОРЯДОК ПОДАЧИ ЗАЯВЛЕНИЯ\n"
            "1. Заявление рассматривается в течение пятнадцати\n"
            "рабочих дней со дня регистрации.",
            "Приложение № 1\n"
            "Заявление на предоставление микрокредита\n"
            "ФИО ________________________",
        ],
    )

    assert [section.title for section in document.sections if section.role == "primary"] == [
        "1. ОБЩИЕ ПОЛОЖЕНИЯ",
        "2. ПОРЯДОК ПОДАЧИ ЗАЯВЛЕНИЯ",
    ]
    first_fact = document.sections[0].facts[0]
    assert "порядок предоставления микрокредитов" in first_fact.value
    assert "под залог имущества" in first_fact.value
    assert first_fact.source_locator.startswith("page=1")
    assert any(section.role == "supporting" for section in document.sections)
