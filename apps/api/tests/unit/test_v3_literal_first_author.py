"""A source-reading hypothesis must not prime the author, while independent audit survives."""
import copy

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value, source_wire
from tests.unit.test_v3_editorial_contract import review_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('literal_first', [False, True])
async def test_original_first_author_does_not_remove_source_analysis_or_independent_checks(case, monkeypatch, literal_first):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, original = case
    view = PracticalModelView(packet)
    events = []

    async def review(_packet, reading, current, *_args, **_kwargs):
        assert reading['interpretations'][0]['rule']['limits'] == ['UNVERIFIED_SOURCE_MAP_SENTINEL']
        events.append('independent-source-and-course-review')
        value = review_value(packet, current)
        value['findings'] = []
        return {'review': value, 'resolutions': [], 'observations': [], 'raw_parts': [], 'source_rule_checks': []}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        value = source_wire(packet, view, fmt, messages)
        if value is not None:
            events.append('source-analysis')
            if fmt['json_schema']['name'] == 'v3_practical_source_semantics_v1':
                value['sections'][0]['rules'][0]['limits'] = ['UNVERIFIED_SOURCE_MAP_SENTINEL']
            validate(value)
            return value
        if name == 'lesson':
            assert ('UNVERIFIED_SOURCE_MAP_SENTINEL' in messages[1]['content']) is (not literal_first)
            assert 'SOURCE_LOGICAL_UNITS_JSON' in messages[1]['content']
            assert 'COURSE_INTENT_JSON' in messages[1]['content']
            for block in packet.blocks:
                assert block.text in messages[1]['content']
            events.append('author')
            value = copy.deepcopy(original)
        else:
            assert 'option-predicates' in group
            assert 'correct_index' not in messages[1]['content']
            events.append('independent-answer-review')
            value = predicate_value(packet, original, fmt=fmt)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage,
        max_revisions=3, joint_editor=True, literal_first_author=literal_first)
    assert result.course == original
    assert events.count('source-analysis') == 3
    assert events.count('author') == 1
    assert 'independent-source-and-course-review' in events
    assert 'independent-answer-review' in events


@pytest.mark.asyncio
@pytest.mark.parametrize('option', ['explicit_edit_scope', 'literal_first_author'])
async def test_new_modes_cannot_silently_change_a_legacy_cycle(option):
    from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

    with pytest.raises(ValueError, match='editorial_joint_policy_invalid'):
        await run_autonomous_editorial_cycle(None, None, None, (), None, max_revisions=3, **{option: True})
