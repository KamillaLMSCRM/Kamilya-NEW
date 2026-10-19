"""Signing projections keep exact event scope in assessment and completeness."""

from app.modules.ai.evidence_engine.assessment_axes import (
    _source_sentences,
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
)
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact

SIGNING = (
    "Подписанием карточки согласования и проставлением отметки о решении "
    "в учетной системе, лицо, согласовавшее операцию, подтверждает принятие "
    "на себя солидарной ответственности в случае несоответствия объекта "
    "и/или размера установленным требованиям."
)


def _fact(value: str) -> SourceFact:
    return SourceFact("signing", "Категория", "Порядок", value,
                      "doc_id=synthetic;source_revision=v1;table=1;row=2;column=2")


def _axes(fact: SourceFact):
    lesson = LessonDraft("signing", "", "", "", "", (fact.fact_id,), (), 1)
    return derive_assessment_axes(lesson, [fact], block_id="signing")


def test_signing_axis_has_exact_responsibility_key_and_joint_event_prompt() -> None:
    fact = _fact(SIGNING)
    axes = _axes(fact)
    assert len(axes) == 1
    assert axes[0].correct_value == (
        "принятие на себя солидарной ответственности в случае несоответствия "
        "объекта и/или размера установленным требованиям"
    )
    assert "Подписанием карточки согласования и проставлением отметки" in axes[0].required_prompt
    assert "лицо, согласовавшее операцию" in axes[0].required_prompt
    assert not has_partial_unatomized_source_contract(fact)


def test_signing_projection_does_not_cover_an_unrelated_parent_sentence() -> None:
    fact = _fact(SIGNING + " Материалы отдельно сверяются с реестром полномочий.")
    assert len(_axes(fact)) == 1
    assert has_partial_unatomized_source_contract(fact)


def test_unsupported_signing_condition_is_not_recast_as_a_mismatch_rule() -> None:
    fact = _fact(SIGNING.replace("в случае несоответствия объекта и/или размера установленным требованиям", "при выполнении операции"))
    assert all(not axis.correct_value.startswith("принятие на себя") for axis in _axes(fact))


def test_terminal_numbered_reference_does_not_absorb_the_next_independent_sentence() -> None:
    first = "Решение требует согласования по телефону, а в дальнейшем в соответствии с п.2."
    second = "Проверку проводят руководители при посещении подразделения."
    assert _source_sentences(first + "  " + second) == [first, second]


def test_inline_numbered_reference_and_city_abbreviation_remain_in_their_sentence() -> None:
    first = "Проверку выполняют согласно п.2. настоящего документа в г. Алматы."
    second = "Результат регистрируется в журнале."
    assert _source_sentences(first + " " + second) == [first, second]


def test_capitalized_legal_reference_continuation_is_not_an_independent_sentence() -> None:
    sentence = "Проверку выполняют согласно п.2. Настоящего документа в г. Алматы."
    assert _source_sentences(sentence) == [sentence]


def test_location_question_preserves_full_inspection_header_without_prior_rule() -> None:
    prior = "Решение требует предварительного согласования по телефону."
    header = "Проверку имущества, его качества и размера операции Контролер проводит"
    value = (prior + " " + header + ": - при размещении пункта в городе - проверка производится во время оперативного контроля. "
             "- при размещении пункта вне города - проверка производится во время комплексного контроля.")
    fact = _fact(value)
    axes = _axes(fact)
    branches = [axis for axis in axes if "при размещении" in axis.required_prompt]
    assert len(branches) == 2
    assert all(header in axis.required_prompt for axis in branches)
    assert all(prior not in axis.required_prompt for axis in branches)
