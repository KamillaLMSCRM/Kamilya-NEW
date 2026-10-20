"""Closed source list decisions must not require padded wrong alternatives."""

from dataclasses import replace

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.quality import answer_containment_option_indices
from app.modules.ai.evidence_engine.semantic_assessment import _course_question_identity


def _axes(value: str):
    fact = SourceFact("rule", "Безопасность", "положение", value, "doc_id=synthetic;part=1")
    lesson = LessonDraft("lesson", "", "", "", "", (fact.fact_id,), (), 1)
    return derive_assessment_axes(lesson, [fact], block_id="scoped")


def test_closed_list_obligation_keeps_actor_condition_and_whole_action():
    clause = "закрыть все окна, форточки"
    items = _axes("Сотрудник, уходящий последним из помещения должен: "
                  f"1) {clause}; 2) закрыть дверь в помещении.")
    item = next(item for item in items if clause in item.required_prompt)
    assert item.correct_value == "должен"
    question = materialize_assessment(item, AuthoredAssessment(item.axis_id, item.required_prompt, ()))
    assert question is not None and question.kind == "true_false"
    assert question.options == ("должен", "не обязан")
    assert "уходящий последним из помещения" in question.prompt
    assert clause in question.prompt
    assert "должен" not in question.prompt
    assert clause in question.explanation
    assert "уходящий последним" in question.explanation
    other = next(axis for axis in items if axis.axis_id != item.axis_id)
    other_question = materialize_assessment(other, AuthoredAssessment(other.axis_id, other.required_prompt, ()))
    assert other_question is not None
    assert _course_question_identity(question, {}) != _course_question_identity(other_question, {})


def test_joint_action_and_exception_are_never_distributed_by_modal_projection():
    clause = "отключить приборы, кроме разрешённых приборов круглосуточного действия"
    items = _axes("Дежурный сотрудник обязан: "
                  f"1) {clause}; 2) закрыть дверь в помещении.")
    item = next(item for item in items if clause in item.required_prompt)
    assert item.correct_value == "обязан"
    question = materialize_assessment(item, AuthoredAssessment(item.axis_id, item.required_prompt, ()))
    assert question is not None and question.options == ("обязан", "не обязан")
    assert clause in question.prompt


def test_ne_dopuskaetsya_list_is_prohibition_not_positive_obligation():
    clause = "устраивать в тамбурах выходов сушилки и вешалки для одежды, а также хранить инвентарь"
    items = _axes("При эксплуатации эвакуационных выходов не допускается: "
                  f"1) {clause}; 2) закрывать проходы мебелью.")
    item = next(item for item in items if clause in item.required_prompt)
    assert item.correct_value == "не допускается"
    question = materialize_assessment(item, AuthoredAssessment(item.axis_id, item.required_prompt, ()))
    assert question is not None and question.options == ("не допускается", "допускается")
    assert answer_containment_option_indices(question) == ()
    assert "не допускается" not in question.prompt


def test_negated_obligation_cannot_grant_positive_modal_truth():
    items = _axes("Сотрудник не должен: 1) закрывать окна; 2) выключать сигнализацию.")
    assert not any(item.correct_value in {"должен", "обязан"} for item in items)


def test_leading_conditions_are_not_relabelled_as_the_actor():
    for prefix in ("При работе на высоте", "Если объявлена тревога,", "После работы", "До проверки",
                   "Перед работой", "Во время смены", "По окончании смены", "Когда объявлена тревога,"):
        items = _axes(f"{prefix} сотрудник обязан: 1) закрыть окна; 2) проверить сигнализацию.")
        assert not any(item.correct_value == "обязан" for item in items)
        assert all(prefix in item.required_prompt for item in items)


def test_unbound_bare_modal_is_not_a_source_owned_list_decision():
    item = _axes("должен")[0]
    assert materialize_assessment(item, AuthoredAssessment(item.axis_id, "Обязательно?", ())) is None


def test_complete_obligation_has_one_whole_predicate_opposite():
    for modal, opposite in (("обязан", "не обязан"), ("обязана", "не обязана"),
                            ("обязано", "не обязано"), ("обязаны", "не обязаны")):
        item = _axes(f"По окончании смены сотрудник {modal} проверить и привести в порядок рабочее место.")[0]
        question = materialize_assessment(item, AuthoredAssessment(item.axis_id, item.required_prompt or "Что нужно сделать?", ()))
        assert question is not None and question.kind == "true_false"
        assert question.options == (f"{modal} проверить и привести в порядок рабочее место", f"{opposite} проверить и привести в порядок рабочее место")
        assert answer_containment_option_indices(question) == ()
        changed = replace(question, options=(question.correct_answer, question.options[1] + " только при согласии"))
        assert answer_containment_option_indices(changed) == (1,)
        ordinary = replace(question, kind="single_choice")
        assert answer_containment_option_indices(ordinary) == (1,)
