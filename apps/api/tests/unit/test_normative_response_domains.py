"""A source-owned proposition is not an invitation to invent extra procedures."""
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    _server_owned_inverse,
    derive_assessment_axes,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.quality import answer_containment_option_indices
from app.modules.ai.evidence_engine.semantic_assessment import _axis_answer_domain


def axes(value):
    fact = SourceFact("f", "Операции", "положение", value, "doc_id=synthetic;part=1")
    lesson = LessonDraft("l", "Правила", "Обязанности", "Применять правила", "", ("f",), (), 1)
    return derive_assessment_axes(lesson, [fact], block_id="b")


def question(axis):
    return materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt or "Как поступить?", ()))


def test_conditional_mark_uses_one_complete_source_verified_opposite():
    condition = "В случае если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику"
    axis = next(a for a in axes(condition + ", то отметка о согласовании не проставляется. "
                                "Экспертам категорически запрещается проводить продление по билету, в случае если операция не согласована контролером.")
                if a.correct_value == "отметка о согласовании не проставляется.")
    q = question(axis)
    assert q is not None and q.kind == "true_false"
    assert condition in q.prompt
    assert q.options == (axis.correct_value, "отметка о согласовании проставляется.")
    # A borrowed answer cannot grant the binary to an unrelated question.
    assert question(replace(axis, required_prompt="Как оформляется передача имущества?")) is None


def test_categorical_prohibition_negates_only_permission_and_keeps_the_entire_condition():
    value = ("Экспертам категорически запрещается проводить продление по билету, "
             "в случае если операция не согласована контролером.")
    axis = next(a for a in axes(value) if a.correct_value == value)
    q = question(axis)
    assert q is not None and q.kind == "true_false"
    assert q.options == (value, value.replace("категорически запрещается", "разрешается"))
    assert all("в случае если операция не согласована контролером" in s for s in q.options)


@pytest.mark.parametrize("extra", [", кроме согласованных исключений", "; возможны исключения", ", но после проверки разрешено"])
def test_qualified_prohibition_does_not_acquire_a_binary_by_partial_match(extra):
    value = "Экспертам категорически запрещается проводить продление по билету, в случае если операция не согласована контролером" + extra + "."
    assert all((q := question(a)) is None or q.kind != "true_false" for a in axes(value))


def test_shared_duties_have_separate_nonoverlapping_scopes_and_a_required_prevention_opposite():
    value = ("Коллектив и его члены несут солидарную ответственность за прямой действительный ущерб, "
             "а также обязаны бережно относиться к вверенному коллективу имуществу и принимать меры по предотвращению ущерба.")
    selected = axes(value)
    liability = next(a for a in selected if a.correct_value == "солидарную ответственность")
    assert "форму ответственности прямо" in liability.required_prompt
    assert _axis_answer_domain(liability)["kind"] == "expressly_named_value"
    care = next(a for a in selected if a.correct_value.startswith("бережно"))
    assert "отдельно от мер по предотвращению ущерба" in care.required_prompt
    care_q = question(care)
    assert care_q is not None and care_q.kind == "true_false"
    assert care_q.options == (care.correct_value, "не требуется " + care.correct_value)
    prevention = next(a for a in selected if a.correct_value == "принимать меры по предотвращению ущерба")
    q = question(prevention)
    assert q is not None and q.kind == "true_false"
    assert q.options == (prevention.correct_value, "не требуется принимать меры по предотвращению ущерба")
    assert answer_containment_option_indices(q) == ()
    assert answer_containment_option_indices(replace(q, kind="single_choice")) == (1,)
    assert answer_containment_option_indices(replace(q, options=(q.correct_answer, q.options[1] + " после проверки"))) == (1,)
    assert "Коллектив и его члены" in q.prompt
    assert question(replace(prevention, required_prompt="Как обращаться с имуществом?")) is None


def test_named_consequence_is_not_a_statement_that_other_liabilities_are_impossible():
    selected = axes("5. За неисполнение настоящих Стандартов экспертом предусмотрена дисциплинарная ответственность в соответствии с ТК РК.")
    axis = next(a for a in selected if a.correct_value == "дисциплинарная ответственность")
    assert "прямо названо" in axis.required_prompt
    assert _axis_answer_domain(axis)["kind"] == "expressly_named_value"
    assert _axis_answer_domain(replace(axis, required_prompt="Какая ответственность вообще возможна?")) is None


def test_inspection_type_is_asked_as_an_explicit_name_with_locality_preserved():
    value = ("Контролеры проводят согласование операции во время проведения комплексной проверки "
             "приемных пунктов находящихся вне границ населенного пункта нахождения офиса дирекции.")
    axis = next(a for a in axes(value) if a.correct_value == "комплексной проверки")
    assert "прямо названной проверки" in axis.required_prompt
    assert "вне границ" in axis.required_prompt
    assert _axis_answer_domain(axis)["kind"] == "expressly_named_value"


def test_inspection_timing_opposite_denies_the_stated_event_not_all_other_procedures():
    value = "согласование микрокредитов осуществляется во время проведения комплексных проверок."
    axis = next(a for a in axes(value) if a.correct_value == value)
    q = question(axis)
    assert q is not None and q.kind == "true_false"
    assert q.options == (value, "согласование микрокредитов не осуществляется во время проведения комплексных проверок.")
    assert "только" not in " ".join(q.options)


@pytest.mark.parametrize("value", [
    "согласование микрокредитов осуществляется только во время проведения комплексных проверок.",
    "согласование микрокредитов осуществляется во время проведения только комплексных проверок.",
    "согласование микрокредитов осуществляется во время проведения комплексных проверок, кроме согласованных случаев.",
    "согласование микрокредитов осуществляется во время проведения комплексных проверок при условии согласия.",
])
def test_inspection_timing_unknown_qualification_cannot_be_partially_negated(value):
    assert _server_owned_inverse(value) is None
