"""Source-exact approval and explicit-reference projections."""

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.operational_approval import (
    project_operational_approvals,
)
from app.modules.ai.evidence_engine.operational_steps import OperationalProjection


def _fact(sentences: tuple[str, ...]) -> SourceFact:
    return SourceFact(
        "synthetic-operational-approval",
        "Категория операции",
        "согласование",
        " ".join(sentences),
        "doc_id=synthetic;source_revision=v1;section=approval;part=1",
    )


def _assert_exact_spans(sentence: str, projection: OperationalProjection) -> None:
    for span in projection.consumed_spans:
        assert sentence[span.start:span.end] == span.text


def test_projects_phone_preapproval_and_only_the_named_followup_reference() -> None:
    sentence = (
        "Решение о выполнении операций по данной категории требует предварительного "
        "согласования по телефону, а в дальнейшем в соответствии с п.2."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 1
    assert projections[0].step.answer == sentence.partition(", а в дальнейшем")[0]
    assert "согласования по телефону" in projections[0].step.answer
    assert "п.2" not in projections[0].step.answer
    assert "по данной категории" in projections[0].step.required_prompt
    assert "п.2." not in projections[0].step.required_prompt
    assert "содержание п.2" not in projections[0].step.required_prompt.casefold()
    assert all(item.step.consumed_sentence_index == 0 for item in projections)
    assert all(item.step.governing_sentence_index == 0 for item in projections)
    for projection in projections:
        _assert_exact_spans(sentence, projection)


def test_projects_general_approval_prefix_without_consuming_local_branch() -> None:
    prefix = (
        "Операции данной категории требуют обязательного согласования "
        "(подписание карточки и проставление отметки в системе) с Региональным "
        "контролером"
    )
    sentence = (
        f"{prefix}: 1) при расположении пункта в пределах города - контролер "
        "проводит отдельную проверку."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 1
    assert projections[0].step.answer == prefix
    assert "подписание карточки и проставление отметки" in projections[0].step.answer
    assert "Региональным контролером" in projections[0].step.required_prompt
    assert all(span.end <= sentence.index(": 1)") for span in projections[0].consumed_spans)
    _assert_exact_spans(sentence, projections[0])


def test_projects_refusal_with_its_condition_and_same_sentence_local_scope() -> None:
    sentence = (
        "1) при расположении пункта в пределах города - В случае несогласования — "
        "Организация отказывает заявителю в выполнении операции."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 1
    assert projections[0].step.answer == (
        "Организация отказывает заявителю в выполнении операции"
    )
    assert projections[0].step.governing_condition == "В случае несогласования"
    assert "при расположении пункта в пределах города" in (
        projections[0].step.required_prompt
    )
    assert "Организация" in projections[0].step.required_prompt
    _assert_exact_spans(sentence, projections[0])


def test_refusal_inherits_only_the_active_numbered_local_branch() -> None:
    local_branch = (
        "1) при расположении пункта в пределах города - Региональный контролер "
        "проводит осмотр объекта."
    )
    local_success = (
        "Если Региональный контролер согласовывает операцию, то специалист "
        "подписывает карточку."
    )
    local_refusal = (
        "В случае несогласования — Организация отказывает заявителю в выполнении "
        "операции."
    )
    remote_branch = (
        "2) при расположении пункта вне границ города - Региональный контролер "
        "проводит удаленную проверку."
    )
    remote_refusal = (
        "В случае несогласования — Организация отказывает заявителю в удаленной "
        "операции."
    )
    sentences = (
        local_branch,
        local_success,
        local_refusal,
        remote_branch,
        remote_refusal,
    )

    projections = project_operational_approvals(_fact(sentences), sentences)
    refusals = [
        item for item in projections if item.step.answer.startswith("Организация")
    ]

    assert len(refusals) == 2
    assert "при расположении пункта в пределах города" in (
        refusals[0].step.required_prompt
    )
    assert "при расположении пункта вне границ города" in (
        refusals[1].step.required_prompt
    )
    assert refusals[0].consumed_spans[0].sentence_index == 0
    assert refusals[1].consumed_spans[0].sentence_index == 3
    assert all(
        span.text in sentences[span.sentence_index]
        for refusal in refusals
        for span in refusal.consumed_spans
    )


def test_refusal_does_not_inherit_locality_across_an_unrelated_sentence() -> None:
    branch = (
        "1) при расположении пункта в пределах города - Региональный контролер "
        "проводит осмотр объекта."
    )
    unrelated = "Ответственный отдельно закрывает журнал рабочей смены."
    refusal = (
        "В случае несогласования — Организация отказывает заявителю в выполнении "
        "операции."
    )
    sentences = (branch, unrelated, refusal)

    projections = project_operational_approvals(_fact(sentences), sentences)
    refusal_projection = next(
        item for item in projections if item.step.answer.startswith("Организация")
    )

    assert "при расположении пункта" not in refusal_projection.step.required_prompt
    assert all(span.sentence_index == 2 for span in refusal_projection.consumed_spans)


def test_projects_remote_phone_approval_with_locality_actor_and_category() -> None:
    sentence = (
        "Операции по II категории при расположении пункта вне границ города "
        "предварительно согласовываются экспертом по телефону."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 2
    assert projections[0].step.answer == "по телефону"
    assert "II категории" in projections[0].step.required_prompt
    assert "вне границ города" in projections[0].step.required_prompt
    assert "Кем" not in projections[0].step.required_prompt
    _assert_exact_spans(sentence, projections[0])


def test_projects_remote_complex_review_with_actor_and_locality() -> None:
    sentence = (
        "Региональные контролеры проводят согласование операции во время проведения "
        "комплексной проверки пунктов находящихся вне границ города."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert len(projections) == 1
    assert projections[0].step.answer == "комплексной проверки"
    assert "Во время какой прямо названной проверки" in projections[0].step.required_prompt
    assert "Региональные контролеры" in projections[0].step.required_prompt
    assert "согласование операции" in projections[0].step.required_prompt
    assert "вне границ города" in projections[0].step.required_prompt
    _assert_exact_spans(sentence, projections[0])


def test_projects_remote_analogy_as_named_reference_without_expansion() -> None:
    sentence = (
        "2) при расположении пункта вне границ города - алгоритм действий "
        "аналогичен процедуре согласования операций I категории."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert projections == ()  # A reference is not an executable procedure.


def test_projects_handover_analogy_with_complete_suspicion_trigger() -> None:
    sentence = (
        "Сменный специалист в случае наличия операций по II категории, во время "
        "приема-передачи подразделения и наличия подозрений в отношении качественных "
        "и/или количественных характеристик объекта должен действовать также как "
        "при приеме-передаче операций I категории."
    )
    sentences = (sentence,)

    projections = project_operational_approvals(_fact(sentences), sentences)

    assert projections == ()  # Do not replace action knowledge with a category label.


def test_rejects_changed_or_disjoint_caller_sentence_sequence() -> None:
    original = (
        "Операции по II категории при расположении пункта вне границ города "
        "предварительно согласовываются экспертом по телефону."
    )
    unrelated = "Специалист отдельно закрывает журнал смены."
    changed = original.replace("вне границ города", "в пределах города")

    assert project_operational_approvals(
        _fact((original, unrelated)),
        (original,),
    ) == ()
    assert project_operational_approvals(_fact((original,)), (changed,)) == ()


def test_rejects_missing_actor_changed_conjunction_and_overlong_targets() -> None:
    missing_actor = (
        "Операции по II категории при расположении пункта вне границ города "
        "предварительно согласовываются по телефону."
    )
    changed_conjunction = (
        "Операции данной категории требуют обязательного согласования "
        "(подписание карточки или проставление отметки в системе) с Региональным "
        "контролером: 1) при расположении пункта в пределах города - выполняется "
        "проверка."
    )
    overlong = (
        "Решение о выполнении "
        + " ".join(["особо детализированных операций"] * 20)
        + " по данной категории требует предварительного согласования по телефону, "
        "а в дальнейшем в соответствии с п.2."
    )

    for sentence in (missing_actor, changed_conjunction, overlong):
        sentences = (sentence,)
        assert project_operational_approvals(_fact(sentences), sentences) == ()
