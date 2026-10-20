"""Observed structural corruption, not ordinary numbering, blocks quality GO."""
import pytest

from app.modules.ai.evidence_engine.models import AssessmentDraft, CourseDraft, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import ProviderBackedEvidenceEngine, _grounded_teaching_text
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


def _render_qualified_block(text, facts):
    lesson = LessonDraft("l", "Правила", "Рабочие правила", "Применять правила", "",
                         tuple(fact.fact_id for fact in facts), (), 2)
    rendered, _, blocks = ProviderBackedEvidenceEngine._validate_and_render(
        {"blocks": [{"heading": "Правила работы", "text": text,
                     "fact_ids": list(lesson.fact_ids)}]},
        base_lesson=lesson, plan_fact_ids=set(lesson.fact_ids),
        facts_by_id={fact.fact_id: fact for fact in facts}, seeds=[],
    )
    return rendered.content, blocks


@pytest.mark.parametrize("paraphrase", [
    "Отступление от утверждённых расценок является нарушением правил оценки.",
    "Отступление от действующих расценок является нарушением правил оценки.",
    "Отступление от расценок является нарушением правил оценки. Действующие инструкции утверждены руководителем.",
    "Утвержденные и действующие инструкции исключают отступление от расценок.",
])
def test_normative_qualifiers_cannot_be_lost_or_borrowed_from_another_object(paraphrase):
    source = ("Отступление от утвержденных и действующих расценок является нарушением правил оценки. "
              "Действующие инструкции утверждены руководителем. "
              + "Установленные правила применяются к работникам организации. " * 18)
    fact = SourceFact("f", "Правила оценки", "обязанность", source,
                      "doc_id=synthetic;section=operations;part=2")
    text, _ = _render_qualified_block(paraphrase, [fact])
    assert paraphrase not in text
    assert "от утвержденных и действующих расценок" in text
    assert "Отступление от утверждённых расценок является" not in text
    assert "Отступление от действующих расценок является" not in text
    assert "Отступление от расценок является" not in text


def test_preserved_normative_qualifiers_keep_supported_paraphrase():
    source = "Отступление от утвержденных и действующих расценок является нарушением правил оценки."
    candidate = "Нарушением правил оценки является отступление от действующих и утвержденных расценок."
    fact = SourceFact("f", "Правила оценки", "обязанность", source,
                      "doc_id=synthetic;section=operations;part=2")
    assert candidate in _render_qualified_block(candidate, [fact])[0]


@pytest.mark.parametrize("second_locator", [
    "doc_id=synthetic;section=operations;part=3",
    "doc_id=synthetic;section=operations;table=1;row=2;column=2",
])
def test_qualification_rejection_uses_normal_per_fact_source_order_and_table_labels(second_locator):
    first = SourceFact("f", "Правила оценки", "обязанность",
        "Отступление от утвержденных и действующих расценок является нарушением правил оценки.",
        "doc_id=synthetic;section=operations;part=2")
    second = SourceFact("g", "Учебная категория", "Размер взноса", "125 рублей", second_locator)
    broad = "Отступление от утвержденных расценок является нарушением правил оценки."
    rendered, blocks = _render_qualified_block(broad, [first, second])
    assert broad not in rendered and first.value in rendered
    assert rendered.index(first.value) < rendered.index(second.value)
    assert [block.fact_ids for block in blocks] == [("f",), ("g",)]
    assert all(block.fact_ids != ("f", "g") for block in blocks)
    if "table=" in second_locator:
        assert "Учебная категория — Размер взноса: 125 рублей." in rendered


@pytest.mark.parametrize("taint", [
    "7. ‚ QRs 8. —",
    "Неверные варианты должны быть правдоподобными.",
])
def test_lost_qualification_with_tainted_source_never_accepts_the_clean_broadened_claim(taint):
    fact = SourceFact("f", "Правила оценки", "обязанность",
        "Отступление от утвержденных и действующих расценок является нарушением правил оценки. " + taint,
        "doc_id=synthetic;section=operations;part=2")
    broad = "Отступление от утвержденных расценок является нарушением правил оценки."
    with pytest.raises(ValueError, match="source qualification"):
        _render_qualified_block(broad, [fact])
