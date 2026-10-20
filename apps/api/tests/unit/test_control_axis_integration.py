from __future__ import annotations

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


@pytest.mark.parametrize(('actor', 'population'), [
    ('Руководитель участка, координаторы смен, старшие специалисты', 'подчиненными им работниками'),
    ('Должностное лицо, назначенное ответственным за организацию пожарной безопасности',
     'всем персоналом организации'),
])
def test_source_control_axis_preserves_named_actor_and_entire_action(actor: str, population: str) -> None:
    verb = 'контролируют' if population.startswith('подчиненными') else 'контролирует'
    value = f'7.2. {actor} {verb} соблюдение Правил пожарной безопасности {population}.'
    fact = SourceFact('control', 'Безопасность', 'положение', value,
                      'doc_id=synthetic;section=responsibility;part=2')
    lesson = LessonDraft('control', 'Безопасность', 'Контроль', '', '', (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id='control')
    assert len(axes) == 1, 'a focused role and its full-sentence fallback are one source target'
    assert axes[0].correct_value == actor
    assert f'{verb} соблюдение Правил пожарной безопасности {population}' in axes[0].required_prompt
    assert axes[0].primary_fact_id == fact.fact_id
