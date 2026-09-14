from app.modules.ai import assessment as assessment_module
from app.modules.ai.assessment import (
    _lesson_assessment_evidence,
    _restored_assessment_is_valid,
    _validate_lesson_entity_scope,
)
from app.modules.ai.assessment_schema import LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.writer_schema import LessonContent


def test_large_table_prioritizes_late_lesson_attributes_without_splitting_columns():
    header = "| Характеристика | Орион | Вега |\n| --- | --- | --- |\n"
    filler = "".join(
        f"| Описание {i} | " + "Декоративное описание изделия. " * 15 + "| Другая серия. |\n" for i in range(24)
    )
    target = "| Материал ручек | Металл с покрытием. | Прочный пластик. |"
    lesson = LessonContent(title="Материалы ручек", source_chunks=[header + filler + target])
    bounded, bank = _lesson_assessment_evidence(lesson)
    assert len(bounded) <= 8000
    assert target in bounded
    assert list(bank.values())[0] == target
    assert "| Характеристика | Орион | Вега |" in bounded
    assert all(quote in bounded for quote in bank.values())


def test_large_comparison_lesson_scopes_by_entity_header_and_keeps_peer_values():
    selected_header = "| Характеристика | Чикаго Стрит |\n| --- | --- |\n"
    selected = selected_header + "".join(
        f"| Описание {index} | " + "Городская модульная система без ручек. " * 10 + "|\n"
        for index in range(40)
    )
    full_header = "| Характеристика | Чикаго Нео | Чикаго Стрит |\n| --- | --- | --- |\n"
    target = "| Направляющие | роликовые | телескопические |"
    lesson = LessonContent(
        title="Коллекция: Чикаго Стрит",
        objectives=["Объяснить характеристики Чикаго Стрит"],
        source_chunks=[selected, full_header + target],
    )

    bounded, bank = _lesson_assessment_evidence(lesson)

    assert full_header.strip() in bounded
    assert target in bounded
    assert list(bank.values()) == [target]
    assert "роликовые" in bounded


def test_entity_card_rejects_question_about_a_different_comparison_column():
    source = (
        "| Характеристика | Чикаго Нео | Чикаго Стрит |\n"
        "| --- | --- | --- |\n"
        "| Кровати | кровать на ламелях | кроватей нет |"
    )
    wrong = {
        "mcq": [{
            "question": "Какая коллекция включает кровать на ламелях?",
            "options": [
                {"text": "Чикаго Нео", "is_correct": True},
                {"text": "Чикаго Стрит", "is_correct": False},
            ],
        }]
    }
    valid = {
        "mcq": [{
            "question": "В какой коллекции из этого сравнения кроватей нет?",
            "options": [
                {"text": "Чикаго Стрит", "is_correct": True},
                {"text": "Чикаго Нео", "is_correct": False},
            ],
        }]
    }

    assert _validate_lesson_entity_scope(wrong, source, "Коллекция: Чикаго Стрит")
    assert not _validate_lesson_entity_scope(valid, source, "Коллекция: Чикаго Стрит")


def test_small_prose_keeps_existing_evidence_contract():
    lesson = LessonContent(title="Поставка", source_chunks=["Срок поставки составляет семь рабочих дней."])
    bounded, bank = _lesson_assessment_evidence(lesson)
    assert bounded == lesson.source_chunks[0]
    assert bank == {"E01": bounded}


def test_ranking_does_not_add_lesson_authored_facts_to_source():
    source = "| Поле | Орион | Вега |\n| --- | --- | --- |\n" + (
        "| Материал | Металл с покрытием. | Прочный пластик. |\n" * 180
    )
    lesson = LessonContent(title="Материал", content="Выдуманная гарантия сто лет.", source_chunks=[source])
    bounded, bank = _lesson_assessment_evidence(lesson)
    assert "гарантия" not in bounded
    assert len(bank) == 1


def test_restore_rebuilds_late_row_scoped_evidence_for_large_table(monkeypatch) -> None:
    header = "| Характеристика | Орион | Вега |\n| --- | --- | --- |\n"
    filler = "".join(f"| Описание {index} | Декоративное описание изделия. | Другая серия. |\n" for index in range(220))
    target = "| Материал ручек | Металл с покрытием. | Прочный пластик. |"
    lesson = LessonContent(title="Материалы ручек", source_chunks=[header + filler + target])
    source_quote = "Материал ручек — Металл с покрытием. — Прочный пластик."
    restored = LessonAssessment(
        lesson_title=lesson.title,
        mcq=[
            MCQQuestion(
                question="Какой материал ручек указан для Орион?",
                options=[
                    MCQOption(text="Металл с покрытием", is_correct=True),
                    MCQOption(text="Матовый алюминий", is_correct=False),
                    MCQOption(text="Латунь без покрытия", is_correct=False),
                    MCQOption(text="Натуральная кожа", is_correct=False),
                ],
                explanation=source_quote,
                source_quote=source_quote,
            )
        ],
    )

    captured = {}

    def capture_validation(data, evidence_bank, bounded_source, *_args):
        captured["evidence_bank"] = evidence_bank
        captured["bounded_source"] = bounded_source
        return []

    monkeypatch.setattr(assessment_module, "_validate_question_evidence", capture_validation)
    monkeypatch.setattr(assessment_module, "_validate_generated_question_set", lambda *_args: [])
    monkeypatch.setattr(assessment_module, "_validate_assessment", lambda *_args: [])

    assert _restored_assessment_is_valid(
        restored,
        lesson,
        language="ru",
        compact=True,
        excluded_fact_keys=frozenset(),
    )
    assert captured["evidence_bank"] == {"E01": target}
    assert target in captured["bounded_source"]
    assert header.strip() in captured["bounded_source"]
