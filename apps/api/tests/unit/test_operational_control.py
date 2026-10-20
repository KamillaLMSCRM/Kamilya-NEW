"""Source-exact actor/control responsibility projections."""

import pytest

from app.modules.ai.evidence_engine.operational_control import (
    project_control_responsibility,
)


def test_projects_every_listed_actor_and_the_complete_control_population() -> None:
    value = (
        "Руководитель участка, координаторы смен, старшие специалисты контролируют "
        "соблюдение Правил пожарной безопасности подчиненными им работниками."
    )

    projected = project_control_responsibility(value)

    assert projected == (
        "Руководитель участка, координаторы смен, старшие специалисты",
        (
            "Какой полный перечень лиц прямо указан в источнике для действия "
            "«контролируют соблюдение Правил пожарной безопасности подчиненными "
            "им работниками»?"
        ),
    )
    assert projected[0] not in {
        "Руководитель участка",
        "координаторы смен",
        "старшие специалисты",
        "Руководитель участка, координаторы смен",
        "координаторы смен, старшие специалисты",
    }


def test_preserves_the_complete_appointed_actor_qualification() -> None:
    value = (
        "Должностное лицо, назначенное ответственным за организацию пожарной "
        "безопасности, контролирует соблюдение Правил пожарной безопасности всем "
        "персоналом организации."
    )

    projected = project_control_responsibility(value)

    assert projected == (
        (
            "Должностное лицо, назначенное ответственным за организацию пожарной "
            "безопасности"
        ),
        (
            "Какой полный перечень лиц прямо указан в источнике для действия "
            "«контролирует соблюдение Правил пожарной безопасности всем персоналом "
            "организации»?"
        ),
    )


@pytest.mark.parametrize(
    "value",
    [
        (
            "Руководитель участка не контролирует соблюдение правил "
            "подчиненными им работниками."
        ),
        (
            "Ежедневно руководитель участка контролирует соблюдение правил "
            "подчиненными им работниками."
        ),
        (
            "При проведении смены руководитель участка контролирует соблюдение "
            "правил подчиненными им работниками."
        ),
        (
            "Руководитель участка или старший специалист контролирует соблюдение "
            "правил подчиненными им работниками."
        ),
        "Он контролирует соблюдение правил всем персоналом организации.",
        (
            "Руководитель участка должен контролировать соблюдение правил "
            "подчиненными им работниками."
        ),
        (
            "Руководитель участка контролировал соблюдение правил подчиненными "
            "им работниками."
        ),
        (
            "Руководитель участка контролирует соблюдение правил подчиненными им "
            "работниками. Специалист фиксирует результат."
        ),
        (
            "Руководитель участка контролирует соблюдение правил подчиненными им "
            "работниками при проведении смены."
        ),
        (
            "Руководитель участка контролирует соблюдение Правил выполнить нормы "
            "пожарной безопасности подчиненными им работниками."
        ),
    ],
)
def test_rejects_negation_conditions_ambiguous_actors_and_nonclosed_rules(
    value: str,
) -> None:
    assert project_control_responsibility(value) is None


def test_rejects_an_actor_key_longer_than_the_assessment_limit() -> None:
    actor = "Руководитель " + " ".join(["старшего участка"] * 18)
    value = (
        f"{actor} контролирует соблюдение правил подчиненными им работниками."
    )

    assert len(actor) > 240
    assert project_control_responsibility(value) is None


def test_prompt_limit_keeps_the_full_action_or_rejects_it_without_truncation() -> None:
    bounded_scope = "Правил " + " ".join(["детализированной"] * 30) + " безопасности"
    bounded_value = (
        "Руководитель участка контролирует соблюдение "
        f"{bounded_scope} подчиненными им работниками."
    )
    overlong_scope = "Правил " + " ".join(["детализированной"] * 48) + " безопасности"
    overlong_value = (
        "Руководитель участка контролирует соблюдение "
        f"{overlong_scope} подчиненными им работниками."
    )

    bounded = project_control_responsibility(bounded_value)

    assert bounded is not None
    assert bounded_scope in bounded[1]
    assert len(bounded[1]) <= 900
    assert project_control_responsibility(overlong_value) is None
