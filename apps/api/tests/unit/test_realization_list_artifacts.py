"""Observed structural corruption, not ordinary numbering, blocks quality GO."""
import pytest

from app.modules.ai.evidence_engine.models import AssessmentDraft, CourseDraft, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import _grounded_teaching_text
from app.modules.ai.evidence_engine.provider_models import GroundedBlock
from app.modules.ai.evidence_engine.quality import (
    contains_ocr_artifact,
    contains_visible_artifact,
    evaluate_publishability,
)


@pytest.mark.parametrize("value", [
    "7. ‚ QRs 8. —",
    ", QRs 8.\n### Раздел",
    "от 09. 14 г.",
    "Условие: 6.\n- действие",
    "Условие; 11.\n\n### Раздел",
    "\n6. 3. Действие",
])
def test_observed_structural_corruption_is_not_publishable(value: str) -> None:
    lesson = LessonDraft("l", "Правила", "Правила работы", "Применять правила",
                         value, ("f",), (), 2)
    report = evaluate_publishability(
        course=CourseDraft("Правила", "", (lesson,)),
        assessment=AssessmentDraft(()),
        blocks=(GroundedBlock("l", "Правила", value, ("f",)),),
        planned_fact_ids={"f"}, provider_fallback_count=0,
    )
    assert report.publishable is False
    assert "visible_ocr_artifacts" in report.reasons


@pytest.mark.parametrize("value", [
    "6. -выполнить действие; 7. -проверить результат",
    "8. — выполнить действие; 9. — проверить результат",
    "от 09.06.14 г.",
    "от 09. 06. 14 г.",
    "Настроить QRs по инструкции",
    "Пункт 1.5. Действие",
    "### Порядок\n1. Проверить выход\n2. Закрыть окно",
])
def test_attached_lists_dates_and_technical_abbreviations_remain_valid(value: str) -> None:
    assert not contains_visible_artifact(value)


@pytest.mark.parametrize("date", ["09.06.14", "09. 06. 14", "09.06.2014"])
def test_missing_source_sentence_is_restored_without_splitting_its_date(date: str) -> None:
    fact = SourceFact("f", "Правила", "обязанность", (
        "Порядок " + ("соблюдения обязательных требований безопасности " * 30)
        + f"установлен приказом № 1276 от {date} г. "
        "Персонал обязан соблюдать требования безопасности."
    ), "doc_id=synthetic;section=safety;part=1")

    text = _grounded_teaching_text("Персонал обязан соблюдать требования безопасности.", [fact])

    assert date in text
    assert not contains_visible_artifact(text)


def test_visible_structure_gate_does_not_silently_discard_source_rules() -> None:
    from app.modules.ai.evidence_engine.engine import admit_document_facts
    from app.modules.ai.evidence_engine.models import SourceDocument, SourceSection
    value = "Сотрудникам запрещается: 7. ‚ QRs 8. — оставлять приборы включенными."
    fact = SourceFact("f", "Правила", "запрет", value,
                      "doc_id=synthetic;section=safety;part=1")
    source = SourceDocument("synthetic", "Правила", "narrative",
                            (SourceSection("safety", "Правила", "primary", (fact,)),),
                            "hash", 1)
    assert not contains_ocr_artifact(value)
    assert contains_visible_artifact(value)
    admitted, _supporting, _duplicates = admit_document_facts(source)
    assert [row.value for row in admitted] == [fact.value]


@pytest.mark.parametrize("marker", ["1.5.", "2.1."])
def test_partial_paraphrase_of_numbered_clause_keeps_the_critical_condition(marker: str) -> None:
    source = (
        f"{marker} Перед выдачей сотрудник обязан проверить номер заявления. "
        "При отсутствии заявления выдача запрещена. "
        + "Установленные требования безопасности обязательны для всех сотрудников. " * 16
    )
    fact = SourceFact("f", "Рабочие правила", "обязанность", source,
                      "doc_id=synthetic;section=operations;part=1")

    text = _grounded_teaching_text(
        "Перед выдачей сотрудник обязан проверить номер заявления.", [fact],
    )

    assert "Перед выдачей сотрудник обязан проверить номер заявления." in text
    assert "При отсутствии заявления выдача запрещена." in text
    assert not contains_visible_artifact(text)
