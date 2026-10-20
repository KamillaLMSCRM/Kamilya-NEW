"""Numbered branch scope must survive coordinated approval/signing targets."""
from app.modules.ai.evidence_engine.assessment_axes import assessment_required_prompt, derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


def _axes():
    value = (
        "Порядок согласования:\n"
        "1) при расположении пункта в границах города - контролер проводит осмотр имущества. "
        "Если контролер согласовывает операцию, то согласовавшее лицо подписывает карточку "
        "с отметкой о согласовании в день оформления и выдачи операции, а также проставляет "
        "отметку в учетной системе.\n"
        "2) при расположении пункта вне границ города - используется отдельная процедура. "
        "Контролер проводит проверку во время выездного осмотра."
    )
    fact = SourceFact("branch", "II категория", "Согласование", value, "table=1;row=2;column=2")
    lesson = LessonDraft("lesson", "", "", "", "", (fact.fact_id,), (), 1)
    return derive_assessment_axes(lesson, [fact], block_id="branches")


def test_both_coordinated_steps_keep_exact_numbered_locality():
    steps = [a for a in _axes() if a.correct_value.startswith(("подписывает", "проставляет"))]
    assert len(steps) == 2
    assert all("при расположении пункта в границах города" in assessment_required_prompt(a) for a in steps)
    assert all("вне границ города" not in assessment_required_prompt(a) for a in steps)


def test_signing_day_is_question_scope_not_an_overlong_action_key():
    axis = next(a for a in _axes() if a.correct_value.startswith("подписывает"))
    assert axis.correct_value == "подписывает карточку с отметкой о согласовании"
    assert "в день оформления и выдачи операции" in assessment_required_prompt(axis)
    assert axis.axis_kind == "rule_value"


def test_nested_number_without_condition_never_erases_outer_locality():
    from app.modules.ai.evidence_engine.assessment_axes import _numbered_action_scope
    fact = SourceFact("nested", "Категория", "Порядок", (
        "1) при расположении пункта в городе - предусмотрены действия:\n"
        "1.1) Проверка проводится ответственным лицом. Если проверка успешна, "
        "то контролер подписывает карточку, а также проставляет отметку в системе."
    ), "table=1;row=2;column=2")
    assert _numbered_action_scope(fact, "подписывает карточку") is None


def test_global_numbered_action_without_any_location_header_retains_global_scope():
    from app.modules.ai.evidence_engine.assessment_axes import _numbered_action_scope
    fact = SourceFact("global", "Категория", "Порядок", (
        "1. Проверка проводится ответственным лицом.\n"
        "2. Если проверка успешна, то контролер подписывает карточку, "
        "а также проставляет отметку в системе."
    ), "table=1;row=2;column=2")
    assert _numbered_action_scope(fact, "подписывает карточку") == ""
