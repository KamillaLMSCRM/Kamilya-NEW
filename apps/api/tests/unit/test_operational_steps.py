"""Typed source-span projections for dependent operational follow-ups."""

import pytest

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.operational_steps import (
    OperationalStep,
    project_rejection_followups,
)


def _fact(sentences: tuple[str, ...]) -> SourceFact:
    return SourceFact(
        "synthetic-rejection-chain",
        "Порядок отказа",
        "обязанность",
        " ".join(sentences),
        "doc_id=synthetic;source_revision=v1;section=rejection;part=1",
    )


def _chain() -> tuple[str, ...]:
    return (
        "Если контролер не согласовывает операцию, то в карточке проставляется отметка об отказе.",
        "В этом случае составляется Акт несоответствия с расчетом допустимого значения.",
        "С специалиста, выдавшего документ, берется объяснительная и обязательство.",
        "Акты несоответствия предоставляются в отдел контроля, на основании которых несогласованные документы вносятся в Стоп-лист.",
    )


def test_projects_each_exact_dependent_step_with_one_governing_condition() -> None:
    sentences = _chain()

    steps = project_rejection_followups(_fact(sentences), sentences)

    assert steps == (
        OperationalStep(
            answer="составляется Акт несоответствия с расчетом допустимого значения",
            required_prompt=(
                "Какой документ оформляется и что он должен содержать при условии "
                "«Если контролер не согласовывает операцию»?"
            ),
            consumed_sentence_index=1,
            governing_sentence_index=0,
            governing_condition="Если контролер не согласовывает операцию",
        ),
        OperationalStep(
            answer=(
                "С специалиста, выдавшего документ, берется объяснительная и "
                "обязательство"
            ),
            required_prompt=(
                "Что необходимо получить с «специалиста, выдавшего документ» при "
                "условии «Если контролер не согласовывает операцию»?"
            ),
            consumed_sentence_index=2,
            governing_sentence_index=0,
            governing_condition="Если контролер не согласовывает операцию",
        ),
        OperationalStep(
            answer="в отдел контроля",
            required_prompt=(
                "Куда предоставляются «Акты несоответствия» при условии "
                "«Если контролер не согласовывает операцию»?"
            ),
            consumed_sentence_index=3,
            governing_sentence_index=0,
            governing_condition="Если контролер не согласовывает операцию",
        ),
        OperationalStep(
            answer="вносятся в Стоп-лист",
            required_prompt=(
                "Какое действие выполняется с «несогласованные документы» на "
                "основании «Акты несоответствия» при условии "
                "«Если контролер не согласовывает операцию»?"
            ),
            consumed_sentence_index=3,
            governing_sentence_index=0,
            governing_condition="Если контролер не согласовывает операцию",
        ),
    )
    assert all(step.answer in sentences[step.consumed_sentence_index] for step in steps)


def test_stops_before_a_document_pair_that_loses_the_source_and() -> None:
    sentences = list(_chain())
    sentences[2] = "С специалиста, выдавшего документ, берется объяснительная."
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.consumed_sentence_index for step in steps) == (1,)


def test_stops_when_the_source_actor_is_missing() -> None:
    sentences = list(_chain())
    sentences[2] = "Берется объяснительная и обязательство."
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.consumed_sentence_index for step in steps) == (1,)


def test_stops_at_an_unrelated_intervening_action() -> None:
    sentences = list(_chain())
    sentences.insert(2, "Архивариус закрывает журнал текущей смены.")
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.consumed_sentence_index for step in steps) == (1,)


@pytest.mark.parametrize(
    "boundary",
    (
        "Если руководитель подтверждает исключение, то процедура возобновляется.",
        "4. Руководитель рассматривает материалы отдельно.",
    ),
)
def test_stops_at_a_new_condition_or_numbered_branch(boundary: str) -> None:
    sentences = list(_chain())
    sentences[2] = boundary
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.consumed_sentence_index for step in steps) == (1,)


def test_rejects_sentences_that_are_not_exact_ordered_source_spans() -> None:
    sentences = _chain()
    reordered = (sentences[0], sentences[2], sentences[1], sentences[3])

    assert project_rejection_followups(_fact(sentences), reordered) == ()


def test_rejects_a_caller_sequence_that_omits_intervening_source_text() -> None:
    sentences = list(_chain())
    sentences.insert(1, "Архивариус закрывает журнал текущей смены.")
    complete_source = tuple(sentences)
    omitted_intervening = (
        complete_source[0],
        complete_source[2],
        complete_source[3],
        complete_source[4],
    )

    assert project_rejection_followups(
        _fact(complete_source),
        omitted_intervening,
    ) == ()


def test_numbered_trigger_retains_exact_sentence_and_projects_the_chain() -> None:
    sentences = list(_chain())
    sentences[0] = "3. " + sentences[0]
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert len(steps) == 4
    assert {step.governing_condition for step in steps} == {
        "Если контролер не согласовывает операцию"
    }
    assert {step.governing_sentence_index for step in steps} == {0}
    assert sentences[0] in _fact(source).value


def test_two_flows_keep_their_own_trigger_indices_across_a_boundary() -> None:
    first = _chain()
    boundary = ("Архивариус закрывает журнал завершенной процедуры.",)
    second = tuple(
        sentence.replace("контролер", "руководитель").replace(
            "операцию", "исключение"
        )
        for sentence in _chain()
    )
    source = first + boundary + second

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.governing_sentence_index for step in steps) == (
        0,
        0,
        0,
        0,
        5,
        5,
        5,
        5,
    )
    assert tuple(step.consumed_sentence_index for step in steps) == (
        1,
        2,
        3,
        3,
        6,
        7,
        8,
        8,
    )


def test_stops_before_a_different_recipient_document_family() -> None:
    sentences = list(_chain())
    sentences[3] = (
        "Счета проверки предоставляются в отдел контроля, на основании которых "
        "несогласованные документы вносятся в Стоп-лист."
    )
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.consumed_sentence_index for step in steps) == (1, 2)


def test_accepts_source_agreement_typo_for_the_same_act_title() -> None:
    sentences = list(_chain())
    sentences[3] = sentences[3].replace("предоставляются", "предоставляется")
    source = tuple(sentences)

    steps = project_rejection_followups(_fact(source), source)

    assert tuple(step.consumed_sentence_index for step in steps) == (1, 2, 3, 3)


@pytest.mark.parametrize("oversized_part", ("answer", "prompt"))
def test_stops_instead_of_truncating_an_overlong_key_or_prompt(
    oversized_part: str,
) -> None:
    sentences = list(_chain())
    if oversized_part == "answer":
        sentences[1] = "В этом случае составляется Акт " + "несоответствия " * 30 + "."
    else:
        sentences[0] = (
            "Если " + "обязательное условие отсутствует и " * 30
            + "контролер не согласовывает операцию, то в карточке проставляется отметка об отказе."
        )
    source = tuple(sentences)

    assert project_rejection_followups(_fact(source), source) == ()
