"""Current question evidence cannot be replaced by stale prior allegations."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_compact_editorial_cycle import review_editorial_candidate
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_editorial_verification import compile_editorial_verification
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_compact_editorial_contract import case, response
from tests.unit.test_v3_editorial_contract import review_value


def finding_and_value(packet, course, kind='question'):
    target = 'q1' if kind == 'question' else 'l1'
    domain = 'assessment' if kind == 'question' else 'content'
    prior = compile_editorial_review(review_value(packet, course, kind=kind, target=target, domain=domain), packet, course)['findings']
    value = review_value(packet, course)
    value['findings'] = []
    value['resolutions'] = [{'issue_id': prior[0]['issue_id'], 'disposition': 'NEEDS_REVISION',
        'reason': 'Current issue confirmed', 'source_refs': [packet.blocks[0].block_id],
        'source_quote': packet.blocks[0].text, 'course_quote': '', 'source_question': ''}]
    return prior, value


@pytest.mark.parametrize('quote,expected', [('', False), ('OLD_STALE_CHOICE', False), ('CURRENT_CHOICE', True)])
def test_question_revision_requires_literal_current_question_evidence(quote, expected):
    packet, course, _ = case()
    course['lessons'][0]['questions'][0]['choices'][0] = 'CURRENT_CHOICE'
    prior, value = finding_and_value(packet, course)
    value['resolutions'][0]['course_quote'] = quote
    result = compile_editorial_verification(value, packet, course, prior)['resolutions'][0]
    assert result['verified'] is expected


def test_nonmaterial_and_lesson_omission_do_not_require_invented_quote():
    packet, course, _ = case()
    prior, value = finding_and_value(packet, course)
    value['resolutions'][0]['disposition'] = 'NOT_MATERIAL'
    assert compile_editorial_verification(value, packet, course, prior)['resolutions'][0]['verified']
    prior, value = finding_and_value(packet, course, 'lesson')
    assert compile_editorial_verification(value, packet, course, prior)['resolutions'][0]['verified']


@pytest.mark.asyncio
async def test_assessment_prior_carries_exact_current_question_next_to_old_observation():
    packet, course, reading = case()
    old = copy.deepcopy(course)
    prior, _ = finding_and_value(packet, old)
    prior[0]['basis'] = 'Old observation: only the first action was offered.'
    current = copy.deepcopy(old)
    q = current['lessons'][0]['questions'][0]
    q.update(prompt='Which actions apply now?', choices=['First or second', 'Neither', 'Other'], correct_index=0)
    checked = []
    view = PracticalModelView(packet)

    async def call(name, group, messages, fmt, validate):
        props = fmt['json_schema']['schema']['properties']
        value = response(packet, current, reading)
        if 'source_rule_checks' in props:
            ids = props['source_rule_checks']['items']['properties']['rule_id']['enum']
            value['source_rule_checks'] = [row for row in value['source_rule_checks'] if row['rule_id'] in ids]
            if 'resolutions' in props:
                value['resolutions'] = []
        else:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
            assigned = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1])
            row = assigned[0]
            assert row['basis'] == prior[0]['basis']
            snapshot = row['current_target_snapshot']
            assert snapshot['prompt'] == q['prompt']
            assert snapshot['choices'] == q['choices']
            assert snapshot['correct_index'] == q['correct_index']
            checked.append(row['issue_id'])
            value['resolutions'] = [{'issue_id': row['issue_id'], 'disposition': 'NOT_MATERIAL',
                'reason': 'Current question already addresses it.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'course_quote': '', 'source_question': ''}]
        validate(value)
        return value

    await review_editorial_candidate(packet, reading, current, 'Original source', view, call,
        'Review', max_rules=128, prior=prior, assessment_system='Assess', verification_guide='Verify')
    assert checked == [prior[0]['issue_id']]
