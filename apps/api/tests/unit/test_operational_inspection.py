"""Source-exact operational inspection and checklist projections."""

import pytest

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.operational_inspection import (
    ExactSentenceSpan,
    OperationalInspectionProjection,
    project_operational_inspections,
)


def _fact(sentences: tuple[str, ...]) -> SourceFact:
    return SourceFact(
        "synthetic-operational-inspection",
        "Категория проверки",
        "обязанность",
        " ".join(sentences),
        "doc_id=synthetic;source_revision=v1;section=inspection;part=1",
    )


def _checklist_sentence(*, final_item: str = "подлинности") -> str:
    return (
        "Во время согласования операции Региональный контролер 1. должен посетить "
        "пункт в установленные сроки и проверить объект на соответствие: - описанию, "
        "- весу, - пробе, - категории, - правильности определения параметра, его "
        f"значения согласно действующим правилам, его {final_item}."
    )


def _local_branch_sentence(*, prefix: str = "") -> str:
    return (
        f"{prefix}1) при расположении пункта в пределах города - Региональный "
        "контролер проводит осмотр, проверку объекта совместно с экспертом, "
        "определяет размер операции в соответствии с действующими категориями и "
        "расценками."
    )


def _assert_exact_spans(
    sentence: str,
    projection: OperationalInspectionProjection,
) -> None:
    for span in projection.consumed_spans:
        assert span.sentence_index == projection.step.consumed_sentence_index
        assert sentence[span.start:span.end] == span.text


def test_projects_complete_visit_and_full_checklist_with_shared_scope() -> None:
    sentence = _checklist_sentence(final_item="качества и/или количества")
    sentences = (sentence,)

    projections = project_operational_inspections(_fact(sentences), sentences)

    assert tuple(item.step.answer for item in projections) == (
        "должен посетить пункт в установленные сроки",
        (
            "проверить объект на соответствие: - описанию, - весу, - пробе, "
            "- категории, - правильности определения параметра, его значения "
            "согласно действующим правилам, его качества и/или количества"
        ),
    )
    assert all(item.step.consumed_sentence_index == 0 for item in projections)
    assert all(item.step.governing_sentence_index == 0 for item in projections)
    assert all(
        item.step.governing_condition == "Во время согласования операции"
        for item in projections
    )
    assert all("Региональный контролер" in item.step.required_prompt for item in projections)
    assert all("Во время согласования операции" in item.step.required_prompt for item in projections)
    assert "и/или" in projections[1].step.answer
    assert projections[1].step.answer.count("- ") == 5
    for projection in projections:
        _assert_exact_spans(sentence, projection)


def test_local_branch_preserves_locality_actor_coactor_and_qualification() -> None:
    independent_prefix = "Общее правило регистрации применяется ко всем операциям: "
    sentence = _local_branch_sentence(prefix=independent_prefix)
    sentences = (sentence,)

    projections = project_operational_inspections(_fact(sentences), sentences)

    assert tuple(item.step.answer for item in projections) == (
        "проводит осмотр, проверку объекта совместно с экспертом",
        (
            "определяет размер операции в соответствии с действующими категориями "
            "и расценками"
        ),
    )
    assert all(
        item.step.governing_condition == "при расположении пункта в пределах города"
        for item in projections
    )
    assert "Региональный контролер" in projections[0].step.required_prompt
    assert "экспертом" in projections[0].step.required_prompt
    assert "действующими категориями и расценками" in projections[1].step.answer
    assert "определяет размер операции" in projections[1].step.required_prompt
    consumed_text = {
        span.text
        for projection in projections
        for span in projection.consumed_spans
    }
    assert independent_prefix.rstrip() not in consumed_text
    assert all(
        span.start >= len(independent_prefix)
        for projection in projections
        for span in projection.consumed_spans
    )
    for projection in projections:
        _assert_exact_spans(sentence, projection)


def test_exact_span_contract_is_immutable() -> None:
    span = ExactSentenceSpan(0, 0, 5, "точно")

    with pytest.raises((AttributeError, TypeError)):
        span.text = "изменено"  # type: ignore[misc]


def test_rejects_an_incomplete_or_fragmented_checklist() -> None:
    sentence = _checklist_sentence().replace(
        ", его подлинности.",
        ", -.",
    )
    sentences = (sentence,)

    assert project_operational_inspections(_fact(sentences), sentences) == ()


def test_rejects_local_branch_without_an_explicit_coactor() -> None:
    sentence = _local_branch_sentence().replace(" совместно с экспертом", "")
    sentences = (sentence,)

    assert project_operational_inspections(_fact(sentences), sentences) == ()


def test_rejects_ambiguous_local_branch_actor() -> None:
    sentence = _local_branch_sentence().replace(
        "Региональный контролер проводит",
        "Региональный контролер или эксперт проводит",
    )
    sentences = (sentence,)

    assert project_operational_inspections(_fact(sentences), sentences) == ()


def test_rejects_an_overlong_group_instead_of_returning_a_partial_sentence() -> None:
    sentence = _checklist_sentence().replace(
        "правильности определения параметра",
        " ".join(["правильности определения дополнительного параметра"] * 10),
    )
    sentences = (sentence,)

    assert project_operational_inspections(_fact(sentences), sentences) == ()


def test_rejects_omitted_or_disjoint_canonical_source_sentences() -> None:
    checklist = _checklist_sentence()
    branch = _local_branch_sentence()
    complete = (
        checklist,
        "Контролер отдельно закрывает журнал смены.",
        branch,
    )
    omitted = (complete[0], complete[2])

    assert project_operational_inspections(_fact(complete), omitted) == ()
