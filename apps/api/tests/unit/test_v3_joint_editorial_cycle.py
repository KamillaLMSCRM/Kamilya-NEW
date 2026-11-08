import copy
import json

import pytest

from app.modules.ai.v3.practical_compact_editorial_cycle import review_editorial_candidate
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_compact_editorial_contract import case, response
from tests.unit.test_v3_editorial_contract import review_value


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid_proof', [False, True])
async def test_joint_resolves_mixed_prior_and_fresh_partial_without_losing_custody(invalid_proof):
    packet, course, reading = case()
    course['lessons'][0]['questions'][0]['prompt'] = 'EXCLUSIVE_QUIZ_PROMPT'
    prior = compile_editorial_review(review_value(packet, course), packet, course)['findings']
    source = copy.deepcopy(prior[0])
    source.update(issue_id='source-prior', domain='source', target={'kind': 'source', 'id': packet.blocks[0].block_id})
    prior.append(source)
    calls = []

    async def call(_name, group, messages, fmt, validate):
        calls.append(group)
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        proof = ':proof:' in group
        if prose:
            assert ':v34:' in group and 'EXCLUSIVE_QUIZ_PROMPT' not in messages[1]['content']
            assert 'PRIOR_MATERIAL_FINDINGS_JSON' not in messages[1]['content']
            value = response(packet, course, reading)
            value['source_rule_checks'][0].update(status='INCOMPLETE', severity='material', correction='Teach action.')
        else:
            value = review_value(packet, course)
            value['findings'] = []
            listed = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1].split('\n')[0])
            if not proof:
                assert 'EXCLUSIVE_QUIZ_PROMPT' in messages[1]['content']
                assert len(listed) == 3
                assert messages[0]['content'].startswith('Whole current course editor')
                assert 'LEGACY_ASSESSMENT_SPECIALIST' not in messages[0]['content']
            value['resolutions'] = [{'issue_id': item['issue_id'], 'disposition': 'NOT_MATERIAL',
                'reason': 'Current source supports dismissal.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': 'bad quote' if invalid_proof else packet.blocks[0].text,
                'course_quote': '', 'source_question': ''} for item in listed]
        validate(value)
        return value

    out = await review_editorial_candidate(packet, reading, course, 'ORIGINAL SOURCE', PracticalModelView(packet),
        call, 'Prose review', max_rules=128, prior=prior, assessment_system='LEGACY_ASSESSMENT_SPECIALIST',
        verification_guide='Verify', joint_editor=True, joint_editor_system='Whole current course editor')
    assert len(out['observations']) == 1 and out['observations'][0]['rule_check_unverified']
    assert len(out['resolutions']) == 3
    assert out['raw_parts'][0]['response']['source_rule_checks'][0]['status'] == 'INCOMPLETE'
    assert any(part['review_kind'] == 'joint_editor' for part in out['raw_parts'])
    if invalid_proof:
        assert any(not row['verified'] for row in out['resolutions'])
        assert any(row['issue_id'] == out['observations'][0]['issue_id'] for row in out['review']['findings'])
        assert any(':v34:proof:' in group for group in calls)
    else:
        assert all(row['verified'] for row in out['resolutions'])
        assert out['review']['findings'] == []


@pytest.mark.asyncio
async def test_joint_initial_partial_finding_is_still_adjudicated():
    packet, course, reading = case()
    calls = []
    async def call(_name, group, messages, fmt, validate):
        calls.append(group)
        if fmt['json_schema']['name'].startswith('v3_practical_compact'):
            value = response(packet, course, reading)
            value['source_rule_checks'][0].update(status='INCOMPLETE', severity='material', correction='Teach action.')
        else:
            value = review_value(packet, course)
            value['findings'] = []
            prior = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1].split('\n')[0])
            value['resolutions'] = [{'issue_id': item['issue_id'], 'disposition': 'NOT_MATERIAL',
                'reason': 'Not material.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'course_quote': '', 'source_question': ''} for item in prior]
        validate(value)
        return value
    out = await review_editorial_candidate(packet, reading, course, 'source', PracticalModelView(packet), call,
        'Review', max_rules=128, assessment_system='Assess', verification_guide='Verify', joint_editor=True)
    assert len(out['observations']) == len(out['resolutions']) == 1
    assert out['resolutions'][0]['verified'] and out['review']['findings'] == []
