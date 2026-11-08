"""Joint editorial observations require current full-editor decisions."""
import copy

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value, source_wire
from tests.unit.test_v3_editorial_contract import review_value, revision_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['closed', 'unresolved', 'owner', 'fresh', 'legacy'])
async def test_joint_observation_decisions_precede_writing(case, monkeypatch, mode):
    import app.modules.ai.v3.practical_autonomous_editorial_cycle as cycle

    corpus, packet, original = case
    candidate = copy.deepcopy(original)
    view = PracticalModelView(packet)
    finding = compile_editorial_review(review_value(packet, original), packet, original)['findings'][0]
    finding['rule_check_unverified'] = True
    fresh = {**copy.deepcopy(finding), 'issue_id': 'fresh-observation'}
    events = []

    async def review(packet, reading, current, context, view, call, system, *, prior=None, **kwargs):
        assert kwargs.get('joint_editor', False) is (mode != 'legacy')
        events.append('initial' if prior is None else 'verify')
        new_observations = [finding] if prior is None else ([fresh] if mode == 'fresh' else [])
        rows = (new_observations if prior is None else [*prior, *new_observations])
        resolutions = []
        for row in rows:
            disposition = ('SOURCE_AMBIGUITY' if mode == 'owner' else
                'UNRESOLVED' if mode == 'unresolved' else
                'NEEDS_REVISION' if mode == 'fresh' and prior is None else 'NOT_MATERIAL')
            resolutions.append({'issue_id': row['issue_id'], 'disposition': disposition,
                'reason': 'Full current assessment', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'course_quote': '',
                'source_question': 'Which rule applies?' if mode == 'owner' else '',
                'verified': mode != 'unresolved', 'verification_errors': ['unresolved'] if mode == 'unresolved' else []})
        findings = [finding] if mode == 'fresh' and prior is None else []
        return {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': cycle._digest(current),
            'summary': 'Reviewed', 'findings': findings, 'source_notes': [],
            'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in current['lessons']}},
            'source_rule_checks': [], 'raw_parts': [], 'observations': new_observations,
            'resolutions': resolutions if mode != 'legacy' else []}

    monkeypatch.setattr(cycle, 'review_editorial_candidate', review)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        if name == 'lesson':
            value = original
        elif 'option-predicates' in group:
            value = predicate_value(packet, candidate, fmt=fmt)
        elif ':revision:' in group:
            assert mode == 'fresh' and events == ['initial']
            events.append('writer')
            candidate['lessons'][0]['questions'][0]['prompt'] = 'Current repaired question?'
            value = revision_value(packet, original, candidate)
        else:
            raise AssertionError(group)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await cycle.run_autonomous_editorial_cycle(
        packet, corpus, CourseIntent(), (), stage, max_revisions=3, joint_editor=mode != 'legacy')
    if mode == 'legacy':
        assert result.decision.accepted and 'initial_joint_observations' not in result.history[0]
        return
    history = result.history[0]
    assert history['initial_joint_observations'][0]['issue_id'] == finding['issue_id']
    assert history['initial_joint_resolutions'][0]['issue_id'] == finding['issue_id']
    if mode == 'unresolved':
        assert not result.decision.accepted and events == ['initial', 'verify']
    elif mode == 'owner':
        assert result.decision.source_uncertain and not result.decision.accepted
        assert events == ['initial'] and history['confirmed_source_questions'][0]['issue_ids'] == [finding['issue_id']]
    elif mode == 'fresh':
        assert result.decision.accepted and events == ['initial', 'writer', 'verify']
        assert any(row['issue_id'] == fresh['issue_id'] for row in history['all_material_findings'])
    else:
        assert result.decision.accepted and events == ['initial']
