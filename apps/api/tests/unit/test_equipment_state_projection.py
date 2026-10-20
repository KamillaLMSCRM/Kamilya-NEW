from __future__ import annotations

import pytest

from app.modules.ai.evidence_engine import assessment_axes
from app.modules.ai.evidence_engine.assessment_axes import (
    _simple_list_obligation_axis,
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
)
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


def _fact(preamble: str, duty: str) -> SourceFact:
    return SourceFact('equipment', 'Безопасность', 'обязанность',
                      f'{preamble}:\n-{duty};\n-организовать обучение сотрудников;',
                      'doc_id=synthetic;section=safety;part=1')


@pytest.mark.parametrize('verb', ['обеспечить', 'обеспечение'])
def test_whole_equipment_state_is_a_focused_source_owned_target(verb: str) -> None:
    duty = f'{verb} исправное состояние технических средств борьбы с пожарами'
    fact = _fact('Руководитель обязан', duty)
    lesson = LessonDraft('safety', 'Безопасность', 'Средства', '', '', (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id='equipment')
    matches = [axis for axis in axes if 'технических средств борьбы с пожарами' in axis.required_prompt]
    assert len(matches) == 1
    assert matches[0].correct_value == 'обязан'
    assert 'Руководитель' in matches[0].required_prompt
    assert 'обеспечить' in matches[0].required_prompt
    assert 'исправное состояние' in matches[0].required_prompt


@pytest.mark.parametrize('preamble', ['Руководитель не обязан', 'Если назначен руководитель обязан'])
def test_unknown_or_negated_parent_cannot_promote_nominal_equipment_duty(preamble: str) -> None:
    duty = 'обеспечение исправное состояние технических средств борьбы с пожарами'
    assert _simple_list_obligation_axis(_fact(preamble, duty), duty) is None


def test_nominal_equipment_duty_preserves_complete_coordinated_object() -> None:
    duty = 'обеспечение исправное состояние систем тушения и средств связи'
    result = _simple_list_obligation_axis(_fact('Ответственные лица обязаны', duty), duty)
    assert result is not None
    assert result[0] == 'обязаны'
    assert 'систем тушения и средств связи' in result[1]


def test_unknown_state_does_not_get_silently_rewritten_to_serviceable() -> None:
    duty = 'обеспечение техническое состояние систем тушения'
    assert _simple_list_obligation_axis(_fact('Руководитель обязан', duty), duty) is None


def test_exact_nominal_duty_is_covered_without_changing_source_words() -> None:
    duty = 'обеспечение исправное состояние технических средств борьбы с пожарами'
    fact = _fact('Руководитель обязан', duty)
    original = fact.value
    assert not has_partial_unatomized_source_contract(fact)
    assert fact.value == original


def test_a_sibling_modal_does_not_claim_a_missing_nominal_duty(monkeypatch: pytest.MonkeyPatch) -> None:
    duty = 'обеспечение исправное состояние технических средств борьбы с пожарами'
    fact = _fact('Руководитель обязан', duty)
    original_derive = assessment_axes.derive_assessment_axes

    def omit_equipment(*args: object, **kwargs: object) -> tuple:
        return tuple(axis for axis in original_derive(*args, **kwargs)
                     if 'технических средств борьбы с пожарами' not in axis.required_prompt)

    monkeypatch.setattr(assessment_axes, 'derive_assessment_axes', omit_equipment)
    assert has_partial_unatomized_source_contract(fact)
