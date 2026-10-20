from __future__ import annotations

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.reference_selection import (
    project_reference_selections,
)


def _fact(value: str, subject: str = "Операции по II категории") -> SourceFact:
    return SourceFact(
        "synthetic-reference", subject, "порядок", value,
        "doc_id=synthetic;source_revision=v1;section=selection;part=1",
    )


def _assert_spans(sentence: str, selection) -> None:
    for span in selection.consumed_spans:
        assert sentence[span.start:span.end] == span.text


def test_projects_remote_selection_for_multiple_named_categories() -> None:
    for category in ("I", "IV", "VII"):
        sentence = (
            "при расположении пункта вне границ города - алгоритм действий "
            f"аналогичен процедуре согласования операций {category} категории."
        )
        result = project_reference_selections(_fact(sentence), (sentence,))
        assert len(result) == 1
        selection = result[0]
        assert selection.kind == "selection"
        assert selection.reference_kind == "remote_analogy"
        assert selection.answer.endswith(f"{category} категории")
        assert selection.unresolved_procedure_content is True
        assert "Какую точно названную процедуру" in selection.required_prompt
        assert "действовать" not in selection.required_prompt.casefold()
        _assert_spans(sentence, selection)


def test_remote_selection_may_use_only_an_explicit_subject_category() -> None:
    sentence = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций I категории."
    )
    assert project_reference_selections(
        _fact(sentence, subject="Операции по II категории"), (sentence,)
    )
    assert project_reference_selections(
        _fact(sentence, subject="Операции"), (sentence,)
    ) == ()


def test_projects_handover_selection_with_complete_actor_and_trigger() -> None:
    sentence = (
        "Сменный специалист в случае наличия операций по II категории, во время "
        "приема-передачи подразделения и наличия подозрений в отношении качественных "
        "и/или количественных характеристик объекта должен действовать также как "
        "при приеме-передаче операций I категории."
    )
    result = project_reference_selections(_fact(sentence), (sentence,))
    assert len(result) == 1
    selection = result[0]
    assert selection.reference_kind == "handover_analogy"
    assert selection.answer == "при приеме-передаче операций I категории"
    assert selection.unresolved_procedure_content is True
    assert "Какую точно названную процедуру" in selection.required_prompt
    assert "действовать" not in selection.required_prompt.casefold()
    _assert_spans(sentence, selection)


def test_rejects_incomplete_context_and_missing_category() -> None:
    incomplete = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций."
    )
    no_trigger = (
        "Сменный специалист в случае наличия операций по II категории должен "
        "действовать также как при приеме-передаче операций I категории."
    )
    assert project_reference_selections(_fact(incomplete), (incomplete,)) == ()
    assert project_reference_selections(_fact(no_trigger), (no_trigger,)) == ()


def test_rejects_reference_category_without_source_side_category_value() -> None:
    sentence = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    assert project_reference_selections(_fact(sentence, subject="Операции"), (sentence,)) == ()


def test_rejects_bare_category_word_without_named_value() -> None:
    sentence = (
        "при расположении пункта вне границ города по данной категории - "
        "алгоритм действий аналогичен процедуре согласования операций IV категории."
    )
    assert project_reference_selections(_fact(sentence, subject="Операции"), (sentence,)) == ()


def test_rejects_vague_handover_actors() -> None:
    suffix = (
        " в случае наличия операций по II категории, во время приема-передачи "
        "подразделения и наличия подозрений в отношении характеристик объекта "
        "должен действовать также как при приеме-передаче операций I категории."
    )
    for actor in ("он", "лицо", "это"):
        sentence = actor + suffix
        assert project_reference_selections(_fact(sentence), (sentence,)) == ()


def test_mixed_action_and_analogy_keeps_selection_bounded_to_analogy() -> None:
    action = "Сотрудник фиксирует решение в карточке."
    analogy = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    value = f"{action} {analogy}"
    result = project_reference_selections(_fact(value), (action, analogy))
    assert len(result) == 1
    assert result[0].answer == "процедуре согласования операций IV категории"
    assert all(span.sentence_index == 1 for span in result[0].consumed_spans)


def test_rejects_tampered_or_partial_sentence_sequence() -> None:
    sentence = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций VII категории."
    )
    fact = _fact(sentence + " Дополнительное неподтвержденное продолжение.")
    assert project_reference_selections(fact, (sentence,)) == ()
    assert project_reference_selections(_fact(sentence), (sentence + " изменено",)) == ()


def test_assessment_selects_named_procedure_without_claiming_execution_steps() -> None:
    from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
    from app.modules.ai.evidence_engine.models import LessonDraft
    from app.modules.ai.evidence_engine.operational_approval import project_operational_approvals
    sentence = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    fact = _fact(sentence)
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id="probe")
    assert len(axes) == 1
    assert axes[0].axis_kind == "selection"
    assert axes[0].correct_value == "процедуре согласования операций IV категории"
    assert "выбрать" in axes[0].required_prompt
    assert project_operational_approvals(fact, [sentence]) == ()


def test_untyped_matching_pair_does_not_claim_a_selection_relation() -> None:
    from app.modules.ai.evidence_engine.assessment_axes import _operational_coverage_projections
    from app.modules.ai.evidence_engine.operational_coverage import audit_operational_coverage
    sentence = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    fact = _fact(sentence)
    selection = project_reference_selections(fact, (sentence,))[0]
    pair = (selection.answer, selection.required_prompt)
    projections = _operational_coverage_projections(fact, [sentence], [pair])
    assert audit_operational_coverage([sentence], [pair], projections).uncovered_spans


def test_selection_does_not_clear_an_independent_unprojected_predicate() -> None:
    from app.modules.ai.evidence_engine.assessment_axes import has_partial_unatomized_source_contract
    relation = (
        "при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    fact = _fact(relation + " Расположение приборов обеспечивает свободный доступ к выходу.")
    assert has_partial_unatomized_source_contract(fact)
