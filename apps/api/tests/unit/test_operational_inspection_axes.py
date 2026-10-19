"""Inspection targets retain all criteria and do not cover independent prefixes."""

from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
)
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


def test_bundled_inspection_targets_do_not_consume_independent_general_rule() -> None:
    value = (
        "Операции данной категории требуют обязательного согласования с контролером: "
        "1) при размещении подразделения в пределах города - Контролер проводит осмотр, "
        "проверку имущества совместно с оценщиком, определяет размер операции "
        "в соответствии с действующими категориями и расценками."
    )
    fact = SourceFact("inspection", "Категория", "Процедура", value,
                      "doc_id=synthetic;table=1;row=2;column=2")
    lesson = LessonDraft("inspection", "", "", "", "", (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id="inspection")
    assert len(axes) == 2
    assert {axis.correct_value for axis in axes} == {
        "проводит осмотр, проверку имущества совместно с оценщиком",
        "определяет размер операции в соответствии с действующими категориями и расценками",
    }
    assert all("при размещении подразделения в пределах города" in axis.required_prompt for axis in axes)
    assert has_partial_unatomized_source_contract(fact)
