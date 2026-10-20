"""Exact source-span accounting for admitted operational projections."""

from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.operational_coverage import audit_operational_coverage
from app.modules.ai.evidence_engine.operational_steps import (
    ExactSentenceSpan,
    OperationalProjection,
    OperationalStep,
)


def _projection(
    sentence: str,
    *,
    answer: str,
    prompt: str,
    sentence_index: int = 0,
    spans: tuple[tuple[int, int], ...],
) -> OperationalProjection:
    return OperationalProjection(
        step=OperationalStep(
            answer=answer,
            required_prompt=prompt,
            consumed_sentence_index=sentence_index,
            governing_sentence_index=sentence_index,
            governing_condition="",
        ),
        consumed_spans=tuple(
            ExactSentenceSpan(sentence_index, start, end, sentence[start:end])
            for start, end in spans
        ),
    )


def test_unions_overlapping_exact_spans_and_allows_only_an_internal_and_connector() -> None:
    sentence = "Контролер проверяет объект и регистрирует результат."
    actor_end = len("Контролер")
    check_start = sentence.index("проверяет")
    check_end = check_start + len("проверяет объект")
    record_start = sentence.index("регистрирует")
    record_end = record_start + len("регистрирует результат")
    projections = (
        _projection(
            sentence,
            answer="проверяет объект",
            prompt="Что проверяет контролер?",
            spans=((0, actor_end), (check_start, check_end)),
        ),
        _projection(
            sentence,
            answer="регистрирует результат",
            prompt="Что регистрирует контролер?",
            spans=((0, actor_end), (record_start, record_end)),
        ),
    )

    audit = audit_operational_coverage(
        (sentence,),
        tuple((item.step.answer, item.step.required_prompt) for item in projections),
        projections,
    )

    assert audit.uncovered_spans == ()
    assert audit.uncovered_sentence_indices == ()


def test_suppressed_target_does_not_contribute_its_spans() -> None:
    sentence = "Контролер проверяет объект и регистрирует результат."
    actor_end = len("Контролер")
    check_start = sentence.index("проверяет")
    check_end = check_start + len("проверяет объект")
    record_start = sentence.index("регистрирует")
    record_end = record_start + len("регистрирует результат")
    check = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        spans=((0, actor_end), (check_start, check_end)),
    )
    suppressed = _projection(
        sentence,
        answer="регистрирует результат",
        prompt="Что регистрирует контролер?",
        spans=((0, actor_end), (record_start, record_end)),
    )

    audit = audit_operational_coverage(
        (sentence,),
        ((check.step.answer, check.step.required_prompt),),
        (check, suppressed),
    )

    assert tuple(span.text for span in audit.uncovered_spans) == (
        "и регистрирует результат",
    )
    assert audit.uncovered_sentence_indices == (0,)


@pytest.mark.parametrize("tail,reference_only", [
    (", а в дальнейшем в соответствии с п.2.", True),
    (", а в дальнейшем проверить имущество в соответствии с п.2.", False),
])
def test_naked_section_reference_is_recorded_separately_not_claimed_as_an_action(tail, reference_only):
    prefix = "Решение требует предварительного согласования по телефону"
    sentence = prefix + tail
    projection = _projection(sentence, answer=prefix, prompt="Как согласуют предварительно?",
                             spans=((0, len(prefix)),))
    audit = audit_operational_coverage((sentence,), ((prefix, projection.step.required_prompt),), (projection,))
    assert bool(audit.reference_only_spans) is reference_only
    assert bool(audit.uncovered_spans) is not reference_only
    if reference_only:
        assert audit.reference_only_spans[0].text == "а в дальнейшем в соответствии с п.2"


def test_changed_prompt_is_not_treated_as_the_same_actual_target() -> None:
    sentence = "Контролер проверяет объект."
    projection = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        spans=((0, len(sentence)),),
    )

    audit = audit_operational_coverage(
        (sentence,),
        ((projection.step.answer, "Когда контролер проверяет объект?"),),
        (projection,),
    )

    assert tuple(span.text for span in audit.uncovered_spans) == (
        "Контролер проверяет объект",
    )


def test_independent_prefix_remains_uncovered_when_only_the_branch_is_claimed() -> None:
    prefix = "Общее правило регистрации обязательно: "
    branch = "1) Контролер проверяет объект."
    sentence = prefix + branch
    projection = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        spans=((len(prefix), len(sentence)),),
    )

    audit = audit_operational_coverage(
        (sentence,),
        ((projection.step.answer, projection.step.required_prompt),),
        (projection,),
    )

    assert tuple(span.text for span in audit.uncovered_spans) == (
        "Общее правило регистрации обязательно",
    )


def test_unknown_inline_number_is_material_between_two_claimed_targets() -> None:
    sentence = "Контролер проверяет объект 42 и регистрирует результат."
    actor_end = len("Контролер")
    check_start = sentence.index("проверяет")
    check_end = check_start + len("проверяет объект")
    record_start = sentence.index("регистрирует")
    record_end = record_start + len("регистрирует результат")
    projections = (
        _projection(
            sentence,
            answer="проверяет объект",
            prompt="Что проверяет контролер?",
            spans=((0, actor_end), (check_start, check_end)),
        ),
        _projection(
            sentence,
            answer="регистрирует результат",
            prompt="Что регистрирует контролер?",
            spans=((0, actor_end), (record_start, record_end)),
        ),
    )

    audit = audit_operational_coverage(
        (sentence,),
        tuple((item.step.answer, item.step.required_prompt) for item in projections),
        projections,
    )

    assert tuple(span.text for span in audit.uncovered_spans) == ("42 и",)


def test_unknown_suffix_is_not_hidden_by_an_earlier_claim() -> None:
    known = "Контролер проверяет объект."
    sentence = known + " Неизвестное требование 7."
    projection = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        spans=((0, len(known)),),
    )

    audit = audit_operational_coverage(
        (sentence,),
        ((projection.step.answer, projection.step.required_prompt),),
        (projection,),
    )

    assert tuple(span.text for span in audit.uncovered_spans) == (
        "Неизвестное требование 7",
    )


@pytest.mark.parametrize(
    "bad_span",
    (
        ExactSentenceSpan(0, 0, 10, "не тот текст"),
        ExactSentenceSpan(0, -1, 5, ""),
        ExactSentenceSpan(3, 0, 5, "Контр"),
    ),
)
def test_malformed_span_invalidates_the_whole_projection(bad_span: ExactSentenceSpan) -> None:
    sentence = "Контролер проверяет объект."
    projection = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        spans=((0, len(sentence)),),
    )
    projection = replace(projection, consumed_spans=(bad_span,))

    audit = audit_operational_coverage(
        (sentence,),
        ((projection.step.answer, projection.step.required_prompt),),
        (projection,),
    )

    assert tuple(span.text for span in audit.uncovered_spans) == (
        "Контролер проверяет объект",
    )


def test_one_actual_pair_cannot_cover_two_duplicate_source_occurrences() -> None:
    sentence = "Контролер проверяет объект."
    first = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        sentence_index=0,
        spans=((0, len(sentence)),),
    )
    second = _projection(
        sentence,
        answer="проверяет объект",
        prompt="Что проверяет контролер?",
        sentence_index=1,
        spans=((0, len(sentence)),),
    )

    audit = audit_operational_coverage(
        (sentence, sentence),
        ((first.step.answer, first.step.required_prompt),),
        (first, second),
    )

    assert tuple(span.sentence_index for span in audit.uncovered_spans) == (1,)
    assert audit.uncovered_sentence_indices == (1,)


def test_ordinal_only_and_punctuation_only_sentences_are_not_material() -> None:
    audit = audit_operational_coverage(("2.", "— (…)"), (), ())

    assert audit.uncovered_spans == ()
    assert audit.uncovered_sentence_indices == ()


def test_and_is_material_when_it_is_not_between_two_claimed_spans() -> None:
    audit = audit_operational_coverage(("и",), (), ())

    assert tuple(span.text for span in audit.uncovered_spans) == ("и",)
    assert audit.uncovered_sentence_indices == (0,)
