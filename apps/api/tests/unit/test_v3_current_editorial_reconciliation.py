import copy
import json

import pytest

from app.modules.ai.v3.practical_current_reconciliation import (
    finish_current_reconciliation,
    reconcile_current_editorial,
    validate_reconciled_current_evidence,
)
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_editorial_verification import compile_editorial_verification
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_editorial_contract import review_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def scenario(packet, course):
    raw = review_value(packet, course, kind='lesson', target='l1', domain='content')
    prior = compile_editorial_review(raw, packet, course)['findings']
    prior[0]['historical_internal_state'] = 'OBSOLETE_SENTINEL'
    value = review_value(packet, course)
    value['findings'] = []
    value['resolutions'] = [{
        'issue_id': prior[0]['issue_id'], 'disposition': 'NEEDS_REVISION',
        'reason': 'Earlier reviewer alleged an omission.',
        'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
        'course_quote': '', 'source_question': '',
    }]
    compiled = compile_editorial_verification(value, packet, course, prior)
    compiled.update(source_rule_checks=[], observations=[], raw_parts=[])
    return prior, value, compiled


@pytest.mark.asyncio
@pytest.mark.parametrize('disposition', ['ALREADY_COVERED', 'NEEDS_REVISION', 'SOURCE_AMBIGUITY'])
async def test_current_model_decides_without_rewriting_or_suppressing_history(case, disposition):
    _, packet, course = case
    prior, value, compiled = scenario(packet, course)
    compiled['source_rule_checks'] = [
        {'rule_id': 'R1', 'status': 'SUPPORTED', 'reason': 'Actual current teaching.',
         'lesson_quotes': [{'lesson_id': 'l1', 'quote': course['lessons'][0]['content']}],
         'internal_history': 'UNRELATED_PROOF_INTERNAL_SENTINEL'},
        {'rule_id': 'R2', 'status': 'SUPPORTED', 'reason': 'UNRELATED_LESSON_SENTINEL',
         'lesson_quotes': [{'lesson_id': 'foreign-lesson', 'quote': 'Not current owned prose.'}]},
    ]
    before = copy.deepcopy((course, prior, compiled))
    value['resolutions'][0].update(disposition=disposition, reason='Compared current source and course.',
        course_quote=course['lessons'][0]['content'],
        source_question='Which of the two source meanings applies?' if disposition == 'SOURCE_AMBIGUITY' else '')
    calls = []

    async def call(stage, group, messages, fmt, validate):
        calls.append(group)
        assert stage == 'review' and group.startswith('practical:editorial:verify:v34:joint:')
        assert 'OBSOLETE_SENTINEL' not in messages[1]['content']
        assert 'UNRELATED_PROOF_INTERNAL_SENTINEL' not in messages[1]['content']
        assert 'UNRELATED_LESSON_SENTINEL' not in messages[1]['content']
        assert course['lessons'][0]['content'] in messages[1]['content']
        assert fmt['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum'] == [prior[0]['issue_id']]
        validate(value)
        return value

    result, effective_prior = await reconcile_current_editorial(
        packet, course, prior, compiled, 'SOURCE CONTEXT', PracticalModelView(packet), call)
    assert len(calls) == 1 and (course, prior, compiled) == before
    assert effective_prior == prior
    assert result['resolutions'][0]['disposition'] == disposition
    assert result['resolutions'][0]['verified'] is True
    assert result['raw_parts'][-1]['review_kind'] == 'addressed_current_editor'
    assert result['raw_parts'][-1]['original_resolutions'] == compiled['resolutions']


@pytest.mark.asyncio
async def test_confirmed_current_closures_do_not_launch_another_model(case):
    _, packet, course = case
    prior, _, compiled = scenario(packet, course)
    compiled['resolutions'][0].update(disposition='ALREADY_COVERED', verified=True)

    async def forbidden(*args):
        raise AssertionError('closed work must not be reviewed again')

    result, _ = await reconcile_current_editorial(
        packet, course, prior, compiled, '', PracticalModelView(packet), forbidden)
    assert result == compiled


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['missing', 'foreign', 'stale'])
async def test_reconciliation_keeps_strict_identity_contract(case, fault):
    _, packet, course = case
    prior, value, compiled = scenario(packet, course)
    if fault == 'missing':
        value['resolutions'] = []
    elif fault == 'foreign':
        value['resolutions'][0]['issue_id'] = 'foreign'
    else:
        value['course_fingerprint'] = 'stale'

    async def call(stage, group, messages, fmt, validate):
        validate(value)
        return value

    with pytest.raises(ValueError, match='editorial_verification_response_invalid'):
        await reconcile_current_editorial(
            packet, course, prior, compiled, '', PracticalModelView(packet), call)


@pytest.mark.parametrize('quote_kind', ['prose', 'quiz', 'missing'])
def test_nonmaterial_course_claim_requires_current_domain_evidence(case, quote_kind):
    _, packet, course = case
    prior, _, compiled = scenario(packet, course)
    row = compiled['resolutions'][0]
    row.update(disposition='NOT_MATERIAL', verified=True, verification_errors=[],
        course_quote=course['lessons'][0]['content'] if quote_kind == 'prose' else
        course['lessons'][0]['questions'][0]['prompt'] if quote_kind == 'quiz' else '')
    compiled['current_reconciliation'] = {'current_quote_issue_ids': [row['issue_id']]}
    validate_reconciled_current_evidence(compiled, course, prior)
    assert row['verified'] is (quote_kind == 'prose')
    assert ('current_nonmaterial_evidence_missing' in row['verification_errors']) is (quote_kind != 'prose')


@pytest.mark.asyncio
async def test_new_primary_observation_is_resolved_and_retained_in_history(case):
    _, packet, course = case
    prior, value, compiled = scenario(packet, course)
    compiled['review']['findings'] = copy.deepcopy(prior)
    compiled['resolutions'] = []
    value['resolutions'][0].update(disposition='ALREADY_COVERED', course_quote=course['lessons'][0]['content'])

    async def call(stage, group, messages, fmt, validate):
        validate(value)
        return value

    result, effective = await reconcile_current_editorial(
        packet, course, [], compiled, '', PracticalModelView(packet), call)
    assert effective == prior and result['review']['findings'] == []
    assert result['observations'] == prior
    assert result['raw_parts'][0]['original_primary_findings'] == prior


@pytest.mark.asyncio
async def test_an_actual_new_model_defect_is_not_lost_when_an_old_claim_closes(case):
    _, packet, course = case
    prior, value, compiled = scenario(packet, course)
    value['resolutions'][0].update(disposition='ALREADY_COVERED', course_quote=course['lessons'][0]['content'])
    value['findings'] = copy.deepcopy(review_value(packet, course)['findings'])

    async def call(stage, group, messages, fmt, validate):
        validate(value)
        return value

    result, _ = await reconcile_current_editorial(
        packet, course, prior, compiled, '', PracticalModelView(packet), call)
    assert result['resolutions'][0]['verified']
    assert len(result['review']['findings']) == 1
    assert result['review']['findings'][0]['problem'] == value['findings'][0]['problem']


@pytest.mark.asyncio
async def test_joint_current_review_closes_a_bad_partial_observation_before_writing():
    from app.modules.ai.v3.practical_compact_editorial_cycle import review_editorial_candidate
    from tests.unit.test_v3_compact_editorial_contract import case, response

    packet, course, reading = case()
    calls = []

    async def call(stage, group, messages, fmt, validate):
        calls.append(group)
        if fmt['json_schema']['name'].startswith('v3_practical_compact'):
            value = response(packet, course, reading)
            value['source_rule_checks'][0].update(status='INCOMPLETE', correction='An earlier omission claim.')
        else:
            value = review_value(packet, course)
            value['findings'] = []
            ids = fmt['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum']
            current = 'UNRESOLVED_ALLEGATIONS_JSON' in messages[1]['content']
            value['resolutions'] = [{
                'issue_id': key, 'disposition': 'ALREADY_COVERED' if current else 'NEEDS_REVISION',
                'reason': 'Re-read actual current prose.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'course_quote': course['lessons'][0]['content'],
                'source_question': '',
            } for key in ids]
        validate(value)
        return value

    result = await review_editorial_candidate(
        packet, reading, course, 'Full source', PracticalModelView(packet), call, 'Review prose',
        max_rules=128, assessment_system='Review course', verification_guide='Current source and course',
        joint_editor=True, addressed_current=True)
    assert len(calls) == 3
    assert result['review']['findings'] == []
    assert result['resolutions'][0]['disposition'] == 'ALREADY_COVERED'
    assert result['resolutions'][0]['verified'] is True
    assert len(result['observations']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['target', 'peer', 'invalid_peer'])
async def test_literal_repair_finishes_an_existing_closure_without_dropping_unproven_work(case, kind):
    from app.modules.ai.v3.practical_editorial_proof_correction import correct_resolution_proofs

    _, packet, original = case
    course = copy.deepcopy(original)
    if kind != 'target':
        peer = copy.deepcopy(course['lessons'][0])
        peer.update(id='l2', title='Current peer lesson')
        for index, question in enumerate(peer['questions']):
            question['id'] = 'peer-question-' + str(index)
        course['lessons'][0]['content'] = 'A different current explanation in the first lesson.'
        course['lessons'].append(peer)
    prior, value, compiled = scenario(packet, course)
    compiled['review']['findings'] = copy.deepcopy(prior)
    value['narrative_sources'] = {lesson['id']: [packet.blocks[0].block_id] for lesson in course['lessons']}
    row = value['resolutions'][0]
    row.update(disposition='ALREADY_COVERED' if kind == 'target' else 'NOT_MATERIAL',
        source_quote='An invalid stitched or paraphrased source quotation.',
        course_quote=course['lessons'][-1]['content'])
    if kind == 'invalid_peer':
        row['course_quote'] = course['lessons'][-1]['questions'][0]['prompt']

    async def semantic(stage, group, messages, fmt, validate):
        validate(value)
        return value

    result, effective = await reconcile_current_editorial(
        packet, course, prior, compiled, '', PracticalModelView(packet), semantic)
    assert not result['resolutions'][0]['verified'] and result['review']['findings']

    async def proof(stage, group, messages, fmt, validate):
        if kind != 'target':
            evidence = json.loads(messages[1]['content'].split('\nELIGIBLE_PROOF_EVIDENCE_JSON\n')[1])
            assert any(course['lessons'][-1]['content'] in target['texts'] for target in evidence['targets'].values())
        repaired = copy.deepcopy(value)
        repaired['resolutions'][0]['source_quote'] = packet.blocks[0].text
        if kind != 'invalid_peer':
            # The model repaired only the bad source quote but omitted an
            # already valid current-course quote, as in the retained native case.
            repaired['resolutions'][0]['course_quote'] = ''
        validate(repaired)
        return repaired

    result = await correct_resolution_proofs(packet, course, effective, result, '',
                                             PracticalModelView(packet), proof, addressed_evidence=True)
    finish_current_reconciliation(result, course, effective)
    assert result['resolutions'][0]['verified'] is (kind != 'invalid_peer')
    assert bool(result['review']['findings']) is (kind == 'invalid_peer')
    assert result['observations'] == prior


@pytest.mark.asyncio
@pytest.mark.parametrize('proposal', ['paraphrase', 'foreign'])
async def test_course_quote_repair_preserves_valid_source_but_never_approves_foreign_ids(case, proposal):
    from app.modules.ai.v3.practical_editorial_proof_correction import correct_resolution_proofs

    _, packet, course = case
    prior, value, compiled = scenario(packet, course)
    compiled['review']['findings'] = copy.deepcopy(prior)
    value['resolutions'][0].update(disposition='ALREADY_COVERED', course_quote='Not current course text.')

    async def semantic(stage, group, messages, fmt, validate):
        validate(value)
        return value

    result, effective = await reconcile_current_editorial(
        packet, course, prior, compiled, '', PracticalModelView(packet), semantic)

    async def proof(stage, group, messages, fmt, validate):
        repaired = copy.deepcopy(value)
        repaired['resolutions'][0].update(course_quote=course['lessons'][0]['content'],
                                         source_quote='An unrequested paraphrase of an already valid quotation.')
        if proposal == 'foreign':
            repaired['resolutions'][0]['source_refs'] = ['foreign-source']
        validate(repaired)
        return repaired

    result = await correct_resolution_proofs(packet, course, effective, result, '',
                                             PracticalModelView(packet), proof, addressed_evidence=True)
    finish_current_reconciliation(result, course, effective)
    assert result['resolutions'][0]['source_quote'] == packet.blocks[0].text
    if proposal == 'foreign':
        assert result['resolutions'][0]['verified'] is False
        assert 'proof_foreign_source_refs' in result['resolutions'][0]['verification_errors']
        assert result['resolutions'][0]['source_refs'] == value['resolutions'][0]['source_refs']
        assert result['review']['findings']
        return
    assert result['resolutions'][0]['verified'] is True
    assert result['resolutions'][0]['retained_valid_proof_fields'] == ['source_quote']
    assert result['review']['findings'] == []
