from dataclasses import FrozenInstanceError

import pytest

from app.modules.ai.evidence_engine.operational_schedule import (
    EVENT_TIME_LITERAL,
    MINIMUM_FREQUENCY_LITERAL,
    InstructionScheduleContract,
    instruction_schedule_option_rejection,
    project_instruction_schedule,
)


def _hiring_contract() -> InstructionScheduleContract:
    contract = project_instruction_schedule(
        "Вновь принимаемые сотрудники",
        "проходят инструктаж по пожарной безопасности",
        "при приеме на работу",
    )
    assert contract is not None
    return contract


def _annual_contract() -> InstructionScheduleContract:
    contract = project_instruction_schedule(
        "сотрудники организации",
        "проходят противопожарный инструктаж",
        "не реже 1 раза в год",
    )
    assert contract is not None
    return contract


def test_hiring_projection_preserves_source_fields_and_uses_literal_event_stem():
    contract = _hiring_contract()

    assert contract.kind == EVENT_TIME_LITERAL
    assert contract.actor == "Вновь принимаемые сотрудники"
    assert contract.activity == "инструктаж по пожарной безопасности"
    assert contract.correct_value == "при приеме на работу"
    assert contract.minimum_yearly_count is None
    assert contract.required_prompt == (
        "Какой именно момент прохождения «инструктаж по пожарной безопасности» прямо "
        "установлен для категории «Вновь принимаемые сотрудники»?"
    )


def test_minimum_frequency_projection_preserves_threshold_and_uses_literal_stem():
    contract = _annual_contract()

    assert contract.kind == MINIMUM_FREQUENCY_LITERAL
    assert contract.actor == "сотрудники организации"
    assert contract.activity == "противопожарный инструктаж"
    assert contract.correct_value == "не реже 1 раза в год"
    assert contract.minimum_yearly_count == 1
    assert contract.required_prompt == (
        "Какая минимальная периодичность прохождения «противопожарный инструктаж» "
        "прямо установлена для категории «сотрудники организации»?"
    )


def test_schedule_contract_is_read_only():
    contract = _annual_contract()

    with pytest.raises(FrozenInstanceError):
        contract.minimum_yearly_count = 4  # type: ignore[misc]


@pytest.mark.parametrize(
    ("actor", "action", "timing"),
    [
        ("", "проходят инструктаж по безопасности", "при приеме на работу"),
        ("сотрудники", " должны проходить инструктаж", "при приеме на работу"),
        ("сотрудники", "должны проходить инструктаж", "при приеме на работу"),
        ("сотрудники", "проходят обучение", "при приеме на работу"),
        ("сотрудники", "проходят инструктаж", "при устройстве на работу"),
        ("сотрудники", "проходят инструктаж", "ежеквартально"),
        ("сотрудники", "проходят инструктаж", "не реже одного раза в год"),
        ("сотрудники\nорганизации", "проходят инструктаж", "при приеме на работу"),
    ],
)
def test_projection_rejects_unknown_or_non_producer_shapes(actor, action, timing):
    assert project_instruction_schedule(actor, action, timing) is None


@pytest.mark.parametrize(
    "option",
    [
        "в течение первого месяца работы",
        "в течение первого месяца работы после трудоустройства",
        "в первый рабочий день",
        "в течение первой рабочей недели",
    ],
)
def test_hiring_contract_rejects_enclosing_windows(option):
    assert instruction_schedule_option_rejection(_hiring_contract(), option) == (
        "instruction_schedule_event_window_includes_required_event"
    )


@pytest.mark.parametrize(
    "option",
    [
        "не реже 1 раза в год после трудоустройства",
        "раз в год",
        "ежеквартально",
        "1 раз в квартал",
    ],
)
def test_hiring_contract_rejects_recurring_schedule_as_nonexclusive(option):
    assert instruction_schedule_option_rejection(_hiring_contract(), option) == (
        "instruction_schedule_recurring_timing_does_not_replace_event"
    )


@pytest.mark.parametrize(
    "option",
    [
        "после завершения первого месяца, без инструктажа при приеме",
        "только спустя месяц после приема на работу",
        "не при приеме на работу, а после допуска к работе",
        "по отдельному графику работодателя",
    ],
)
def test_hiring_contract_leaves_explicit_deferral_and_unknowns_for_audits(option):
    assert instruction_schedule_option_rejection(_hiring_contract(), option) is None


@pytest.mark.parametrize(
    "option",
    [
        "ежемесячно",
        "ежеквартально",
        "ежегодно",
        "один раз в год",
        "два раза в год",
        "три раза в два года",
        "1 раз в год после трудоустройства",
    ],
)
def test_minimum_frequency_rejects_equal_or_stricter_compliant_rates(option):
    assert instruction_schedule_option_rejection(_annual_contract(), option) == (
        "instruction_schedule_frequency_still_meets_minimum"
    )


@pytest.mark.parametrize(
    "option",
    [
        "раз в два года",
        "один раз в два года",
        "реже одного раза в год",
        "только при приеме на работу, без ежегодного повторения",
        "не чаще 1 раза в квартал",
        "не реже 1 раза в год и после каждого инцидента",
        "примерно ежеквартально",
        "1-2 раза в год",
    ],
)
def test_minimum_frequency_leaves_violations_and_unknown_syntax_for_audits(option):
    assert instruction_schedule_option_rejection(_annual_contract(), option) is None
