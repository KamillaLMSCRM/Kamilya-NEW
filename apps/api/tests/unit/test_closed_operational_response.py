from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    assessment_required_prompt,
    derive_assessment_axes,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact


def _axis(source: str, key: str):
    fact = SourceFact("f", "Работа с оборудованием", "положение", source, "doc_id=source")
    lesson = LessonDraft("lesson", "Рабочие правила", "", "", "", ("f",), (), 1)
    return next(axis for axis in derive_assessment_axes(lesson, [fact], block_id="block")
                if axis.correct_value == key)


def test_complete_passive_list_prohibition_has_one_source_owned_opposite() -> None:
    scope = "Эксплуатация нагревателей при отсутствии или неисправности терморегуляторов"
    axis = _axis(f"При эксплуатации оборудования запрещается:\n- пользоваться поврежденными проводами;\n- {scope} не допускается;",
                 "не допускается")
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, axis.required_prompt, ("допускается всегда", "допускается без проверки"),
    ))
    assert question is not None
    assert question.kind == "true_false"
    assert question.options == ("не допускается", "допускается")
    assert scope in question.prompt and scope in question.explanation


@pytest.mark.parametrize("authority", ["руководителем организации", "директором компании",
                                        "начальником подразделения"])
def test_qualified_responsible_person_uses_opposite_of_the_exact_appointment(authority: str) -> None:
    key = f"лицо, назначенное {authority}"
    axis = _axis(f"Ответственность за состояние оборудования возлагается на {key}.", key)
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, axis.required_prompt, ("любой работник", "все сотрудники"),
    ))
    assert question is not None
    assert question.kind == "true_false"
    assert question.options == (key, f"лицо, не назначенное {authority}")
    assert key in question.explanation


@pytest.mark.parametrize("change", ["prompt", "key", "evidence"])
def test_appointment_opposite_requires_exact_source_producer_correspondence(change: str) -> None:
    key = "лицо, назначенное руководителем организации"
    axis = _axis(f"Ответственность за состояние оборудования возлагается на {key}.", key)
    if change == "prompt":
        axis = replace(axis, required_prompt="Кто проверяет журнал?")
    elif change == "key":
        axis = replace(axis, correct_value="лицо, назначенное директором компании",
                       normalized_correct_value="лицо, назначенное директором компании")
    else:
        axis = replace(axis, distractor_constraints=())
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, axis.required_prompt, ("любой работник", "все сотрудники"),
    ))
    assert question is None or question.kind != "true_false"


def test_matching_source_context_prefix_is_not_duplicated() -> None:
    key = "лицо, назначенное руководителем организации"
    axis = _axis(f"Ответственность за состояние оборудования возлагается на {key}.", key)
    axis = replace(axis, source_context="Категория А",
                   required_prompt="Для «Категория А»: На кого возлагается ответственность?")
    assert assessment_required_prompt(axis) == axis.required_prompt


def test_different_source_context_is_not_silently_removed() -> None:
    key = "лицо, назначенное руководителем организации"
    axis = _axis(f"Ответственность за состояние оборудования возлагается на {key}.", key)
    axis = replace(axis, source_context="Категория А",
                   required_prompt="Для «Категория Б»: На кого возлагается ответственность?")
    assert assessment_required_prompt(axis).startswith("Для «Категория А»: Для «Категория Б»:")


@pytest.mark.parametrize("key", [
    "лицо, назначенное руководителем организации и директором компании",
    "лицо, назначенное руководителем организации или директором компании",
    "лицо, назначенное руководителем организации при аварии",
    "лицо, не назначенное руководителем организации",
])
def test_open_or_negative_appointment_scope_never_grants_a_binary_opposite(key: str) -> None:
    axis = _axis(f"Ответственность за состояние оборудования возлагается на {key}.", key)
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, axis.required_prompt, ("любой работник", "все сотрудники"),
    ))
    assert question is None or question.kind != "true_false"
