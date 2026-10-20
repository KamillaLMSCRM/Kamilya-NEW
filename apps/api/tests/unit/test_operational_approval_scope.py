"""Source-scoped approval projections must not invent authority or resolve references."""

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.operational_approval import (
    project_operational_approvals,
)
from app.modules.ai.evidence_engine.operational_steps import OperationalProjection


def _fact(sentences: tuple[str, ...]) -> SourceFact:
    return SourceFact(
        "synthetic-operational-approval-scope",
        "Категория операции",
        "согласование",
        " ".join(sentences),
        "doc_id=synthetic;source_revision=v2;section=approval;part=7",
    )


def _assert_exact_spans(
    sentences: tuple[str, ...], projection: OperationalProjection,
) -> None:
    for span in projection.consumed_spans:
        sentence = sentences[span.sentence_index]
        assert sentence[span.start:span.end] == span.text


def test_phone_preapproval_projects_explicit_method_not_unresolved_reference() -> None:
    sentence = (
        "Решение о выполнении операций по данной категории требует предварительного "
        "согласования по телефону, а в дальнейшем в соответствии с п.7.4."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 1
    projection = projections[0]
    assert projection.step.answer == (
        "Решение о выполнении операций по данной категории требует предварительного "
        "согласования по телефону"
    )
    assert projection.step.governing_condition == (
        "Решение о выполнении операций по данной категории"
    )
    assert "п.7.4" not in projection.step.answer
    assert "п.7.4" not in projection.step.required_prompt
    assert "полный порядок" not in projection.step.required_prompt.casefold()
    assert [span.text for span in projection.consumed_spans] == [projection.step.answer]
    _assert_exact_spans(sentences, projection)


def test_remote_phone_precoordination_projects_method_without_approval_authority() -> None:
    sentence = (
        "Операции по VII категории при расположении пункта вне границ округа "
        "предварительно согласовываются выездным оценщиком по телефону."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 2
    projection, participant = projections
    assert projection.step.answer == "по телефону"
    assert participant.step.answer == "выездным оценщиком"
    assert participant.step.required_prompt == (
        "Кем выполняется именно предварительное согласование по телефону для "
        "«Операции по VII категории при расположении пункта вне границ округа»?"
    )
    assert "утвержд" not in participant.step.required_prompt
    assert projection.step.governing_condition == (
        "Операции по VII категории при расположении пункта вне границ округа"
    )
    prompt = projection.step.required_prompt.casefold()
    assert "vii категории" in prompt
    assert "вне границ округа" in prompt
    assert "выездным оценщиком" not in prompt
    assert "кто" not in prompt
    assert "кем" not in prompt
    assert [span.text for span in projection.consumed_spans] == [
        projection.step.governing_condition,
        projection.step.answer,
    ]
    _assert_exact_spans(sentences, projection)


def test_unresolved_category_analogies_are_not_assessment_projections() -> None:
    remote_reference = (
        "3) при расположении пункта вне границ округа - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    handover_reference = (
        "Сменный специалист в случае наличия операций по VII категории, во время "
        "приема-передачи подразделения и наличия подозрений в отношении качественных "
        "и/или количественных характеристик объекта должен действовать также как "
        "при приеме-передаче операций IV категории."
    )

    for sentence in (remote_reference, handover_reference):
        sentences = (sentence,)
        assert project_operational_approvals(_fact(sentences), sentences) == ()


def test_unresolved_reference_cannot_reenter_through_generic_axis_fallback() -> None:
    from app.modules.ai.evidence_engine.assessment_axes import (
        derive_assessment_axes,
        has_partial_unatomized_source_contract,
    )
    from app.modules.ai.evidence_engine.models import LessonDraft
    value = (
        "3) при расположении пункта вне границ округа - алгоритм действий "
        "аналогичен процедуре согласования операций IV категории."
    )
    fact = _fact((value,))
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    assert derive_assessment_axes(lesson, [fact], block_id="b") == ()
    assert has_partial_unatomized_source_contract(fact)
