"""Recover safe alternatives without treating true source timing as false."""

from dataclasses import replace

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _axis_author_payload


def _axis():
    fact = SourceFact("remote", "II категория", "положение",
        "Согласование операций II категории производят в первый рабочий день с момента выдачи. "
        "Региональные контролеры проводят согласование операции во время проведения комплексной проверки "
        "пунктов находящихся вне границ города.",
        "doc_id=synthetic;table=1;row=2;column=2")
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    return next(axis for axis in derive_assessment_axes(lesson, [fact], block_id="b")
                if axis.correct_value == "комплексной проверки")


def test_author_receives_the_same_true_timing_exclusion_as_local_admission():
    axis = _axis()
    assert _axis_author_payload(axis)["excluded_source_timings"] == ["в первый рабочий день"]


def test_one_source_true_extra_does_not_erase_two_independently_admissible_choices():
    axis = replace(_axis(), source_context="")
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "В первый рабочий день с момента выдачи",
        "Во время оперативной проверки",
        "Только после закрытия пункта",
    )))
    assert question is not None
    assert question.correct_answer == "комплексной проверки"
    assert question.options == (axis.correct_value, "Во время оперативной проверки", "Только после закрытия пункта")


def test_true_timing_is_never_retained_when_only_one_safe_alternative_remains():
    axis = _axis()
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, (
        "В первый рабочий день с момента выдачи", "Во время оперативной проверки",
    )))
    assert question is None
