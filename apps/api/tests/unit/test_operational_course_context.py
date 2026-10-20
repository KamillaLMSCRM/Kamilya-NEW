"""Operational table applicability is source-owned, not an author rephrasing."""
from dataclasses import replace

from app.modules.ai.evidence_engine.assessment_axes import (
    assessment_required_prompt,
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _axis_author_payload,
    _course_question_identity,
)

VALUE = (
    "Подписанием карточки согласования и проставлением отметки о решении "
    "в учетной системе, лицо, согласовавшее операцию, подтверждает принятие "
    "на себя солидарной ответственности в случае несоответствия объекта "
    "и/или размера установленным требованиям."
)


def _fixture(subject: str, identity: str):
    fact = SourceFact(identity, subject, "Порядок", VALUE,
                      f"doc_id=d1;source_revision=v1;section=rules;table=1;row={identity};column=2")
    lesson = LessonDraft("l", "", "", "", "", (identity,), (), 1)
    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, assessment_required_prompt(axis), (
            "принятие ответственности только за сохранность объекта",
            "принятие ответственности только за сроки согласования",
        ),
    ))
    assert question is not None
    return fact, axis, question


def test_source_table_category_is_visible_without_changing_exact_key_or_coverage():
    fact, axis, question = _fixture("I категория", "1")
    assert axis.source_context == fact.subject
    assert question.prompt.startswith("Для «I категория»: ")
    assert question.correct_answer == axis.correct_value
    assert axis.correct_value in fact.value
    assert _axis_author_payload(axis)["required_prompt"] == question.prompt
    assert not has_partial_unatomized_source_contract(fact)


def test_distinct_applicability_survives_but_same_context_still_deduplicates():
    first, first_axis, first_question = _fixture("I категория", "1")
    second, second_axis, second_question = _fixture("II категория", "2")
    facts = {first.fact_id: first, second.fact_id: second}
    assert first_question.correct_answer == second_question.correct_answer
    assert _course_question_identity(first_question, facts, first_axis) != (
        _course_question_identity(second_question, facts, second_axis)
    )
    assert _course_question_identity(first_question, facts, first_axis) == (
        _course_question_identity(replace(first_question, question_id="copy"), facts, first_axis)
    )


def test_untrusted_prompt_or_mismatched_axis_cannot_grant_distinct_identity():
    fact, axis, question = _fixture("I категория", "1")
    facts = {fact.fact_id: fact}
    variants = (
        (replace(question, prompt=question.prompt + " Дополнение автора?"), axis),
        (question, replace(axis, primary_fact_id="other")),
        (question, replace(axis, source_context="II категория")),
        (question, replace(axis, subject="II категория")),
        (question, replace(axis, source_context="")),
    )
    for candidate, candidate_axis in variants:
        assert _course_question_identity(candidate, facts, candidate_axis) == (
            _course_question_identity(candidate, facts)
        )


def test_generic_catalog_dedup_and_numeric_kind_do_not_grant_operational_scope():
    fact = SourceFact("1", "Серия А", "Гарантия", "24 месяца",
                      "doc_id=d1;source_revision=v1;section=catalog;row=1;column=2")
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    axis = derive_assessment_axes(lesson, [fact], block_id="b")[0]
    assert axis.source_context == ""
    assert axis.axis_kind == "numeric_value"


def test_overlong_source_applicability_is_not_truncated_or_accepted():
    fact = SourceFact("1", "Длинная категория " * 60, "Порядок", VALUE,
                      "doc_id=d1;source_revision=v1;section=rules;table=1;row=1;column=2")
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    assert derive_assessment_axes(lesson, [fact], block_id="b") == ()
    assert has_partial_unatomized_source_contract(fact)


def test_one_source_true_distractor_does_not_erase_two_admissible_alternatives():
    fact = SourceFact("1", "I категория", "Порядок", VALUE +
                      " Согласование проводится в первый рабочий день.",
                      "doc_id=d1;source_revision=v1;section=rules;table=1;row=1;column=2")
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    axis = next(axis for axis in derive_assessment_axes(lesson, [fact], block_id="b")
                if axis.correct_value.startswith("принятие на себя"))
    valid = (
        "принятие ответственности только за сохранность объекта",
        "принятие ответственности только за сроки согласования",
    )
    source_true = "Подтверждает согласование в первый рабочий день."
    question = materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, assessment_required_prompt(axis), (*valid, source_true),
    ))
    assert question is not None
    assert question.options == (axis.correct_value, *valid)
    assert source_true not in question.options
    assert not question.semantic_reviewed  # Normal independent review still required.
    assert materialize_assessment(axis, AuthoredAssessment(
        axis.axis_id, assessment_required_prompt(axis), (valid[0], source_true),
    )) is None


def test_source_exception_is_not_false_when_the_general_question_has_a_day_scope():
    fact = SourceFact("f", "Проверка", "Порядок", (
        "Если контролер согласовывает операцию, то контролер подписывает карточку в день оформления, "
        "а также проставляет отметку в системе учета. "
        "Если операция оформляется в выходные, решение согласовывается по телефону. "
        "Карточку подписывают в первый рабочий день."
    ), "doc_id=d;source_revision=v1;section=s;table=1;row=1;column=2")
    lesson = LessonDraft("l", "", "", "", "", ("f",), (), 1)
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id="b")
                if a.correct_value == "подписывает карточку")
    assert "в день оформления" in assessment_required_prompt(axis)
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id,
        assessment_required_prompt(axis), ("Подписывает карточку в первый рабочий день.",
                                           "Оставляет карточку без подписи.")))
    assert question is None
