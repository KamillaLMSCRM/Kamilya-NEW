"""Source-owned event and minimum-frequency questions reject compatible alternatives."""
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _author_shape_rejection_reasons,
    _axis_answer_domain,
    _axis_author_payload,
)

EVENT = "при приеме на работу"
MINIMUM = "не реже 1 раза в год"
SOURCE = (
    "Вновь принимаемые сотрудники проходят инструктаж по пожарной безопасности при приеме на работу. "
    "Сотрудники организации проходят инструктаж не реже 1 раза в год."
)


def schedule_axis(key):
    fact = SourceFact("f", "Инструктаж", "положение", SOURCE, "doc_id=synthetic;part=1")
    lesson = LessonDraft("l", "Инструктаж", "Обязанности", "Применять требования", "", ("f",), (), 1)
    return next(a for a in derive_assessment_axes(lesson, [fact], block_id="b") if a.correct_value == key)


@pytest.mark.parametrize(("key", "kind", "stem"), [
    (EVENT, "event_time_literal", "момент"),
    (MINIMUM, "minimum_frequency_literal", "минимальная периодичность"),
])
def test_source_schedule_owns_exact_key_specific_stem_and_every_author_payload(key, kind, stem):
    axis = schedule_axis(key)
    assert stem in axis.required_prompt
    domain = _axis_answer_domain(axis)
    assert domain is not None and domain["kind"] == kind
    assert _axis_author_payload(axis)["answer_domain"] == domain
    assert _axis_author_payload(axis)["source_claim"] == key
    assert _axis_answer_domain(replace(axis, required_prompt="Когда проводится инструктаж?")) is None
    assert _axis_answer_domain(replace(axis, distractor_constraints=())) is None


@pytest.mark.parametrize(("key", "option", "reason"), [
    (EVENT, "в течение первого месяца работы", "instruction_schedule_event_window_includes_required_event"),
    (EVENT, "не реже 1 раза в год после трудоустройства", "instruction_schedule_recurring_timing_does_not_replace_event"),
    (MINIMUM, "не реже 1 раза в квартал", "instruction_schedule_frequency_still_meets_minimum"),
    (MINIMUM, "не реже 4 раз в год", "instruction_schedule_frequency_still_meets_minimum"),
])
def test_captured_compatible_timing_options_are_rejected_before_paid_blind_review(key, option, reason):
    axis = schedule_axis(key)
    q = QuestionDraft("q", "l", "single_choice", axis.required_prompt,
                      (key, option, "только через два года"), key, SOURCE, "f",
                      evidence_fact_ids=("f",), source_quote=SOURCE)
    assert any(reason in item for item in _author_shape_rejection_reasons(q, axis))
