"""Source-exact signing-event responsibility projections."""

import pytest

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.operational_signing import (
    project_signing_responsibilities,
)
from app.modules.ai.evidence_engine.operational_steps import OperationalStep


def _fact(sentences: tuple[str, ...]) -> SourceFact:
    return SourceFact(
        "synthetic-signing-responsibility",
        "Порядок согласования",
        "ответственность",
        " ".join(sentences),
        "doc_id=synthetic;source_revision=v1;section=signing;part=1",
    )


def _sentence(*, variant: str = "one", actor_typo: bool = False) -> str:
    if variant == "one":
        event = (
            "Подписанием карточки согласования и проставлением отметки о решении "
            "в учетной системе"
        )
    else:
        event = (
            "Подписанием отметки о согласовании карточки, а так же проставлением "
            "отметки о решении в учетной системе"
        )
    separator = ", и " if actor_typo else ", "
    return (
        f"{event}{separator}лицо, согласовавшее операцию, подтверждает принятие "
        "на себя солидарной ответственности в случае несоответствия объекта "
        "и/или размера установленным требованиям."
    )


def test_projects_exact_joint_event_actor_and_complete_mismatch_condition() -> None:
    signing = _sentence()
    sentences = (
        "Решение предварительно фиксируется в журнале.",
        signing,
        "Материалы хранятся в установленном порядке.",
    )
    answer = (
        "принятие на себя солидарной ответственности в случае несоответствия "
        "объекта и/или размера установленным требованиям"
    )
    condition = (
        "в случае несоответствия объекта и/или размера установленным требованиям"
    )
    event = (
        "Подписанием карточки согласования и проставлением отметки о решении "
        "в учетной системе"
    )

    steps = project_signing_responsibilities(_fact(sentences), sentences)

    assert steps == (
        OperationalStep(
            answer=answer,
            required_prompt=(
                "Что подтверждает «лицо, согласовавшее операцию» событием "
                f"«{event}»?"
            ),
            consumed_sentence_index=1,
            governing_sentence_index=1,
            governing_condition=condition,
        ),
    )
    assert answer in signing
    assert event in steps[0].required_prompt
    assert "и/или" in steps[0].answer


@pytest.mark.parametrize(
    ("variant", "actor_typo"),
    (("one", True), ("two", False), ("two", True)),
)
def test_supports_two_joint_event_shapes_and_optional_comma_i_typo(
    variant: str,
    actor_typo: bool,
) -> None:
    signing = _sentence(variant=variant, actor_typo=actor_typo)
    sentences = (signing,)

    steps = project_signing_responsibilities(_fact(sentences), sentences)

    assert len(steps) == 1
    assert steps[0].consumed_sentence_index == 0
    assert steps[0].governing_sentence_index == 0
    assert steps[0].answer in signing
    assert "и/или" in steps[0].governing_condition


def test_rejects_a_signing_sentence_without_the_explicit_responsible_actor() -> None:
    signing = _sentence().replace(
        "лицо, согласовавшее операцию, ",
        "ответственность ",
    )
    sentences = (signing,)

    assert project_signing_responsibilities(_fact(sentences), sentences) == ()


def test_rejects_disjoint_or_omitted_source_sentences() -> None:
    signing = _sentence()
    complete = (
        "Решение фиксируется в журнале.",
        "Контролер отдельно проверяет полномочия ответственного лица.",
        signing,
    )
    omitted = (complete[0], complete[2])

    assert project_signing_responsibilities(_fact(complete), omitted) == ()


def test_rejects_an_overlong_event_context_instead_of_truncating_it() -> None:
    signing = _sentence().replace(
        "карточки согласования",
        "карточки " + "дополнительного согласования " * 40,
    )
    sentences = (signing,)

    assert project_signing_responsibilities(_fact(sentences), sentences) == ()


def test_rejects_responsibility_without_an_explicit_mismatch_condition() -> None:
    signing = _sentence().replace(
        "в случае несоответствия объекта и/или размера установленным требованиям",
        "при выполнении операции",
    )
    sentences = (signing,)

    assert project_signing_responsibilities(_fact(sentences), sentences) == ()


def test_rejects_loss_of_the_joint_signing_and_recording_event() -> None:
    signing = _sentence().replace(
        " и проставлением отметки о решении в учетной системе",
        "",
    )
    sentences = (signing,)

    assert project_signing_responsibilities(_fact(sentences), sentences) == ()
